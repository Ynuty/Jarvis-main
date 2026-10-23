"""
============================================================
 Session — оркестратор одного профиля. Живёт, пока ядро запущено;
 окно интерфейса подключается к ней по WebSocket и может
 переподключаться (таймеры и диалог при этом не теряются).

 Жизненный цикл реплики (рис. 2 в архитектуре):
   ввод → нормализация → [ожидает подтверждения? / активный сценарий?]
        → правила INTENTS → LLM → JSON → политика → подтверждение
        → навык → журнал → ответ текстом + голос по предложениям.

 Слух: PCM16 с микрофона → VAD → Whisper. Пока Джарвис говорит,
 фразы принимаются только как «перебивание» (стоп / Джарвис …).
============================================================
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np
from pydantic import ValidationError

from . import journal
from .db import DB, dumps
from .engines import engines
from .intents import router
from .llm import dialog
from .llm.ollama import OllamaError
from .security import KillSwitch, Risk, check, is_no, is_yes
from .settings import Settings
from .skills.base import TOOLS, Ctx, Reply, ToolResult, invoke, validation_message
from .text.ru import norm
from .voice.tts import SentenceSplitter
from .voice.vad import Segmenter

log = logging.getLogger("jarvis.session")

OPEN_WINDOW = 12.0                      # сек после ответа слушаем без имени
WAKE = re.compile(r"(^|\s)(джарвис\w*|джарвиз|джарвес|джарис|джарв|джарви|jarvis|джервис|жарвис|чарвис|джаврис|"
                  r"дарвис|гарвис|джарвейс|джарвас|джавис|джавес|джявис|жавис|джаавис)(\s|,|$)")
BARGE = re.compile(r"(стоп|хватит|замолчи|тихо|джарвис|отмена)")

MISS = [
    "Не уверен, что понял, сэр. Скажите «что ты умеешь» — покажу список команд.",
    "Такой команды в реестре нет, сэр. Попробуйте иначе.",
    "Не разобрал. Повторите, пожалуйста, чуть медленнее.",
]


def has_wake(text: str) -> bool:
    return bool(WAKE.search(norm(text)))


def strip_wake(text: str) -> str:
    t = WAKE.sub(" ", norm(text))
    t = re.sub(r"^\s*[,:]?\s*(эй|слушай|скажи|пожалуйста)?\s*[,:]?\s*", "", t)
    return re.sub(r"\s+", " ", t).strip(" ,")


@dataclass
class Pending:
    id: str
    title: str
    risk: str
    future: asyncio.Future
    event_id: int = 0


@dataclass
class Timer:
    id: int
    label: str
    message: str
    at: float
    task: asyncio.Task | None = None


class Flow:
    """Многошаговый сценарий навыка (корзина, план сортировки почты)."""
    name = "flow"
    ttl = 180.0

    def __init__(self) -> None:
        self.started = time.time()

    @property
    def expired(self) -> bool:
        return time.time() - self.started > self.ttl

    async def handle(self, ctx: Ctx, text: str) -> Reply | str | None:  # pragma: no cover — интерфейс
        return None


@dataclass
class Stats:
    heard: int = 0
    done: int = 0
    started: float = field(default_factory=time.time)
    mic: bool = False
    last_latency: dict = field(default_factory=dict)


class Session:
    def __init__(self, db: DB, profile_id: int, profile_name: str = "") -> None:
        self.db = db
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.settings = Settings(db, profile_id)
        self.kill = KillSwitch()
        self.pending: Pending | None = None
        self.flow: Flow | None = None
        self.timers: dict[int, Timer] = {}
        self.timer_seq = 0
        self.mode: str = self.settings.get("listen_mode", "wake")
        self.sleeping = False
        self.open_until = 0.0
        self.listening = False
        self.speaking = False
        self.speak_until = 0.0
        self.busy = False
        self.state = "idle"
        self.last_reply = ""
        self.stats = Stats()
        self.volume = 1.0
        self.sinks: list[tuple[Callable[[dict], Awaitable[None]], Callable[[bytes], Awaitable[None]]]] = []
        self.say_q: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self.audio_seq = 0
        self.speaker: asyncio.Task | None = None
        self.turn: asyncio.Task | None = None
        self.segmenter: Segmenter | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.extras: dict[str, Any] = {}   # состояние навыков (последний план почты и т. п.)

    # ================= транспорт =================

    def attach(self, send_json: Callable[[dict], Awaitable[None]], send_bytes: Callable[[bytes], Awaitable[None]]):
        self.loop = asyncio.get_running_loop()
        pair = (send_json, send_bytes)
        self.sinks.append(pair)
        if self._engines_cb not in engines.listeners:
            engines.listeners.append(self._engines_cb)
        if not self.speaker or self.speaker.done():
            self.speaker = asyncio.create_task(self._speaker_loop())
        return pair

    def _engines_cb(self) -> None:
        """Вызывается из потока загрузки моделей — переносим в цикл событий."""
        if self.loop and self.sinks:
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(
                self.emit({"type": "engines", "engines": dict(engines.status), "llm": engines.llm_ok})))

    def detach(self, pair) -> None:
        if pair in self.sinks:
            self.sinks.remove(pair)
        if not self.sinks:
            self.listening = False

    async def emit(self, msg: dict) -> None:
        for send_json, _ in list(self.sinks):
            try:
                await send_json(msg)
            except Exception:  # noqa: BLE001 — окно закрылось посреди отправки
                pass

    async def _emit_bytes(self, data: bytes) -> None:
        for _, send_bytes in list(self.sinks):
            try:
                await send_bytes(data)
            except Exception:  # noqa: BLE001
                pass

    async def set_state(self, state: str) -> None:
        self.state = state
        await self.emit({"type": "status", **self.status_payload()})

    def status_payload(self) -> dict:
        return {"state": self.state, "mode": self.mode, "sleeping": self.sleeping,
                "listening": self.listening, "open": time.time() < self.open_until,
                "speaking": self.speaking, "pending": bool(self.pending),
                "flow": self.flow.name if self.flow else ""}

    async def idle(self) -> None:
        if self.busy:
            return
        await self.set_state("sleep" if self.sleeping else
                             "listen" if (self.listening and time.time() < self.open_until) else "idle")

    # ================= журнал диалога =================

    async def log_line(self, who: str, text: str, kind: str, **extra) -> None:
        await self.emit({"type": "line", "who": who, "text": text, "kind": kind, "ts": time.time(), **extra})

    # ================= голос: вывод =================

    def speak(self, text: str) -> None:
        """Ставит текст в очередь озвучки (режется на предложения)."""
        if not text:
            return
        if not self.speaker or self.speaker.done():      # страховка: очередь озвучки всегда жива
            if self.speaker and self.speaker.done() and not self.speaker.cancelled():
                log.error("очередь озвучки упала: %r", self.speaker.exception())
            self.speaker = asyncio.get_running_loop().create_task(self._speaker_loop())
        sp = SentenceSplitter(min_len=1)
        gen = self.kill.generation
        for s in sp.push(text + " ") + sp.flush():
            self.say_q.put_nowait((gen, s))

    async def _speaker_loop(self) -> None:
        while True:
            try:
                await self._speak_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — озвучка не должна умирать от одной фразы
                log.exception("озвучка")

    async def _speak_one(self) -> None:
        if True:
            gen, text = await self.say_q.get()
            log.info("озвучка: %r (gen %s/%s, окон %s, tts %s)", text[:60], gen, self.kill.generation,
                     len(self.sinks), engines.tts.engine if engines.tts else None)
            if not self.kill.alive(gen) or not self.sinks:
                return
            self.speaking = True
            if self.state not in ("think",):
                await self.set_state("speak")
            for _ in range(150):           # голос ещё грузится — ждём до 15 с, а не молчим
                if not engines.tts_loading:
                    break
                await asyncio.sleep(0.1)
            tts = engines.tts
            wav = b""
            if tts and tts.ready:
                try:
                    wav = await asyncio.to_thread(tts.synth, text)
                except Exception as e:  # noqa: BLE001
                    log.warning("tts: %s", e)
            if not self.kill.alive(gen):
                return
            self.audio_seq += 1
            if wav:
                dur = max(0.3, (len(wav) - 44) / 2 / 22050)
                await self.emit({"type": "audio", "seq": self.audio_seq, "text": text, "volume": self.volume})
                await self._emit_bytes(wav)
            else:
                dur = max(0.8, len(text) / 14)
                await self.emit({"type": "say", "seq": self.audio_seq, "text": text, "volume": self.volume})
            self.speak_until = max(self.speak_until, time.time()) + dur

    async def playback_state(self, playing: bool) -> None:
        """Интерфейс сообщает, что доиграл очередь — снимаем глушение слуха."""
        if not playing and self.say_q.empty():
            self.speaking = False
            self.speak_until = 0
            if not self.sleeping and self.state == "speak":
                self.open_until = time.time() + OPEN_WINDOW
            await self.idle()

    async def shut_up(self) -> None:
        """Тишина и аварийная остановка: обрывает речь, ожидание подтверждения, сценарии."""
        self.kill.trip()
        while not self.say_q.empty():
            self.say_q.get_nowait()
        self.speaking = False
        self.speak_until = 0
        if self.pending and not self.pending.future.done():
            self.pending.future.set_result(False)
        await self.emit({"type": "audio_stop"})

    # ================= голос: ввод =================

    def mic_start(self) -> None:
        if self.segmenter is None:
            self.segmenter = Segmenter(on_start=self._on_speech_start, on_partial=self._on_partial,
                                       on_segment=self._on_segment)
        else:
            self.segmenter.reset()
        self.listening = True
        self.stats.mic = True

    def mic_stop(self) -> None:
        self.listening = False
        if self.segmenter:
            self.segmenter.reset()

    def feed_audio(self, data: bytes) -> None:
        if self.listening and self.segmenter:
            self.segmenter.feed_pcm16(data)

    def _spawn(self, coro) -> None:
        if self.loop:
            self.loop.create_task(coro)

    def _on_speech_start(self) -> None:
        if not self.speaking and not self.busy and not self.sleeping:
            self._spawn(self.set_state("listen"))

    def _on_partial(self, audio: np.ndarray) -> None:
        stt = engines.stt
        if not stt or not stt.ready or self.speaking or self.sleeping:
            return
        self._spawn(self._partial(audio))

    async def _partial(self, audio: np.ndarray) -> None:
        if engines.stt.lock.locked():
            return                              # не копим очередь, живая расшифровка — «по возможности»
        text, _ = await asyncio.to_thread(engines.stt.transcribe, audio[-16000 * 6:], "", True)
        if text:
            await self.emit({"type": "heard", "text": text, "final": False})

    def _on_segment(self, audio: np.ndarray) -> None:
        self._spawn(self._segment(audio))

    async def _segment(self, audio: np.ndarray) -> None:
        stt = engines.stt
        if not stt or not stt.ready:
            return
        t_end = time.perf_counter()
        echo_guard = self.speaking or time.time() < self.speak_until
        text, took = await asyncio.to_thread(stt.transcribe, audio, self.hotwords(), echo_guard)
        if not text:
            return
        if echo_guard:
            # Пока говорим — принимаем только перебивание, остальное считаем эхом.
            if not BARGE.search(norm(text)):
                return
            await self.shut_up()
        self.stats.last_latency["stt"] = round(took, 2)
        self.stats.heard += 1
        await self.emit({"type": "heard", "text": text, "final": True})
        await self.handle_utterance(text, source="voice", t0=t_end)

    def hotwords(self) -> str:
        words = []
        try:
            from .skills import desktop
            words += desktop.app_names()[:30]
        except Exception:  # noqa: BLE001
            pass
        if self.profile_name:
            words.append(self.profile_name)
        return ", ".join(words)

    # ================= маршрутизация реплики =================

    async def handle_utterance(self, raw: str, source: str = "text", t0: float | None = None) -> None:
        t0 = t0 or time.perf_counter()
        text = norm(raw)
        if not text:
            return

        if source == "voice":
            if self.sleeping:
                if has_wake(text) or re.search(r"проснись|подъем", text):
                    await self.log_line("Вы", raw, "user")
                    self.sleeping = False
                    self.open_until = time.time() + OPEN_WINDOW
                    await self.emit({"type": "beep", "name": "wake"})
                    await self._start_turn("проснись", raw, t0)
                return
            wake = has_wake(text)
            in_window = time.time() < self.open_until or bool(self.pending) or bool(self.flow)
            if not wake and not in_window and self.mode == "wake":
                # не к нам — не отвечаем, но и не молчим загадочно: раз в полминуты подсказка
                if time.time() - self.extras.get("wake_hint", 0) > 30:
                    self.extras["wake_hint"] = time.time()
                    await self.log_line("Система", f"Услышал: «{raw}». Чтобы я ответил, начните с «Джарвис» "
                                        "или скажите «Джарвис, слушай постоянно».", "sys")
                return
            cmd = strip_wake(text) if wake else text
            self.open_until = time.time() + OPEN_WINDOW
            if not cmd:
                await self.emit({"type": "beep", "name": "wake"})
                await self.log_line("Вы", raw, "user")
                await self.set_state("listen")
                return
        else:
            self.sleeping = False
            self.open_until = time.time() + OPEN_WINDOW
            cmd = strip_wake(text) if has_wake(text) else text

        await self.log_line("Вы", raw, "user")

        # Ответ на карточку подтверждения — не новый ход.
        if self.pending and not self.pending.future.done():
            if is_yes(cmd) or is_no(cmd):
                self.pending.future.set_result(is_yes(cmd))
                return
            self.pending.future.set_result(False)  # новая команда отменяет ожидание
        await self.emit({"type": "beep", "name": "ack"})
        await self._start_turn(cmd, raw, t0)

    async def _start_turn(self, cmd: str, raw: str, t0: float) -> None:
        # «стоп» обрабатываем мгновенно, не дожидаясь текущего хода
        if re.fullmatch(r"(замолчи|молчи|тихо|хватит|стоп|отставить|прекрати|тише уже|отмена)", cmd):
            await self.shut_up()
            if self.turn and not self.turn.done():
                self.turn.cancel()
            self.flow = None
            await self.log_line("Джарвис", "Тишина.", "jarvis")
            self.busy = False
            await self.idle()
            return
        if self.turn and not self.turn.done():
            await self.shut_up()
            self.turn.cancel()
        self.turn = asyncio.create_task(self.run(cmd, raw, t0))

    async def run(self, text: str, raw: str = "", t0: float | None = None) -> Reply:
        t0 = t0 or time.perf_counter()
        self.busy = True
        await self.set_state("think")
        ctx = Ctx(self, user_text=text, raw_text=raw or text)
        reply: Reply | None = None
        try:
            if self.flow:
                if self.flow.expired:
                    self.flow = None
                else:
                    r = await self.flow.handle(ctx, text)
                    if r is not None:
                        reply = Reply.of(r, "flow:" + self.flow.name if self.flow else "flow")
            if reply is None:
                hit = await router.match(ctx, text)
                if hit is not None:
                    reply = hit
            if reply is None:
                reply = await self._llm_turn(ctx, text, t0)
        except asyncio.CancelledError:
            self.busy = False
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("ход упал")
            reply = Reply(say="Сбой при выполнении, сэр. Подробности в журнале.", intent="error")
            journal.log(self.db, self.profile_id, skill="core", tool="turn", status="failed",
                        result=repr(e), summary="Сбой обработки реплики")
        self.busy = False

        if reply.intent and reply.intent not in ("unknown", "error"):
            self.stats.done += 1
        if reply.say:
            self.last_reply = reply.say
        self.stats.last_latency["turn"] = round(time.perf_counter() - t0, 2)
        if reply.log or reply.say:
            await self.log_line("Джарвис", reply.log or reply.say, "jarvis", intent=reply.intent,
                                data=reply.data, latency=self.stats.last_latency.get("turn"))
        if not reply.silent and reply.intent != "llm-streamed":
            self.speak(reply.say)
        self._remember(text, reply)
        if not self.speaking and self.say_q.empty():
            await self.idle()
        return reply

    def _remember(self, text: str, reply: Reply) -> None:
        if reply.silent or not reply.say:
            return
        now = time.time()
        self.db.run("INSERT INTO messages(profile_id, ts, role, text) VALUES (?,?,?,?)",
                    (self.profile_id, now, "user", text))
        self.db.run("INSERT INTO messages(profile_id, ts, role, text) VALUES (?,?,?,?)",
                    (self.profile_id, now, "assistant", reply.say))
        if self.settings.get("collect_dataset"):
            self.db.run("INSERT INTO dataset(profile_id, ts, messages) VALUES (?,?,?)",
                        (self.profile_id, now, dumps([{"role": "user", "content": text},
                                                      {"role": "assistant", "content": reply.say}])))
        if reply.intent.startswith("llm"):
            from .skills import memory
            self._spawn(memory.after_turn(self, text))

    # ================= LLM =================

    async def _llm_turn(self, ctx: Ctx, text: str, t0: float) -> Reply:
        if not engines.llm_ok:
            ok = await engines.check_llm(self.settings.get("llm_model"))
            if not ok:
                return Reply(say=random.choice(MISS), intent="unknown",
                             log=random.choice(MISS) + f" (нейросеть недоступна: {engines.status['llm']})")

        from .skills import knowledge
        snippets = await knowledge.retrieve_for(ctx, text)
        if snippets:
            ctx.untrusted = True
        msgs = dialog.build_messages(self.db, self.profile_id, self.settings.all(), text, knowledge=snippets)

        splitter = SentenceSplitter()
        gen = self.kill.generation
        first_audio: list[float] = []

        async def on_say(chunk: str) -> None:
            for s in splitter.push(chunk):
                if not first_audio:
                    first_audio.append(time.perf_counter() - t0)
                self.say_q.put_nowait((gen, s))

        try:
            ans = await dialog.respond(engines.ollama, msgs, self.settings.get("llm_model"),
                                       temperature=float(self.settings.get("llm_temperature", 0.6)),
                                       on_say=on_say, alive=lambda: self.kill.alive(gen))
        except OllamaError as e:                         # модель ответила ошибкой — разовый сбой ответа
            log.warning("llm: %s", e)
            return Reply(say="Сбился на полуслове, сэр. Спросите ещё раз, пожалуйста.", intent="error",
                         log=f"Сбой генерации: {e}")
        except Exception as e:  # noqa: BLE001 — нет связи с Ollama
            engines.llm_ok = False
            engines.status["llm"] = f"ошибка: {e}"[:160]
            return Reply(say="Нейросеть не отвечает, сэр. Проверьте, запущена ли Ollama.", intent="error")
        for s in splitter.flush():
            self.say_q.put_nowait((gen, s))
        if first_audio:
            self.stats.last_latency["first_sentence"] = round(first_audio[0], 2)

        if not ans.ok:
            if ans.error == "прервано":
                return Reply(silent=True, intent="cancelled")
            return Reply(say="Боюсь, не понял, сэр. Сформулируйте иначе.", intent="unknown",
                         log=f"Не понял (модель: {ans.error})")

        say = ans.say
        result: ToolResult | None = None
        if ans.action:
            result = await self.call_tool(ctx, ans.action, ans.args, origin="llm", llm_confirm=ans.confirm)
        if result and result.say:
            extra = result.say
            if ans.spoken:
                self.speak(extra)
                return Reply(say=say + " " + extra, log=(say + "\n" + (result.log or extra)).strip(),
                             intent="llm-streamed", data=result.data if isinstance(result.data, dict) else None)
            return Reply(say=(say + " " + extra).strip(), log=(say + "\n" + (result.log or extra)).strip(),
                         intent="llm:" + ans.action)
        return Reply(say=say, log=say, intent="llm-streamed" if ans.spoken else "llm")

    # ================= инструменты =================

    async def call_tool(self, ctx: Ctx, name: str, args: dict, *, origin: str = "rule",
                        llm_confirm: bool = False, preconfirmed: bool = False) -> ToolResult:
        """
        preconfirmed — пользователь уже сказал «да» в сценарии навыка (корзина, план почты).
        Действует только для external и только для внутренних вызовов: danger и предложения
        модели всегда идут через карточку подтверждения.
        """
        t = TOOLS.get(name)
        disabled = set(self.settings.get("disabled_tools", []) or [])
        dec = check(t, ctx.user_text, untrusted=ctx.untrusted, disabled=disabled, origin=origin)
        if t is None:
            return ToolResult(say="Такого действия нет, сэр.", ok=False)
        try:
            parsed = t.parse(args)
        except ValidationError as e:
            return ToolResult(say=f"Не хватает данных: {validation_message(e)}.", ok=False)
        summary = t.human(parsed)
        logged = t.risk != Risk.READ or t.network
        dump = parsed.model_dump() if parsed is not None else {}
        if not dec.allow:
            journal.log(self.db, self.profile_id, skill=t.skill, tool=t.name, args=dump, risk=t.risk.value,
                        status="denied", result=dec.reason, summary=summary, source=origin)
            await self._event_changed()
            return ToolResult(say=f"Не могу, сэр: {dec.reason}", ok=False)

        ev = 0
        if logged:
            ev = journal.log(self.db, self.profile_id, skill=t.skill, tool=t.name, args=dump, risk=t.risk.value,
                             status="planned", summary=summary, source=origin)
        need_confirm = dec.confirm or (llm_confirm and t.risk != Risk.READ)
        if need_confirm and preconfirmed and origin == "auto" and t.risk == Risk.EXTERNAL and not ctx.untrusted:
            need_confirm = False
            if ev:
                journal.update(self.db, ev, "confirmed", "подтверждено в сценарии")
        if need_confirm:
            ok = await self.ask_confirm(summary, t.risk.value, ev)
            if not ok:
                if ev:
                    journal.update(self.db, ev, "cancelled", "пользователь не подтвердил")
                    await self._event_changed()
                return ToolResult(say="Отменено, сэр.", ok=False)
            if ev:
                journal.update(self.db, ev, "confirmed")

        gen = self.kill.generation
        try:
            res = await invoke(t, ctx, parsed)
        except Exception as e:  # noqa: BLE001
            log.exception("инструмент %s", name)
            if ev:
                journal.update(self.db, ev, "failed", repr(e))
                await self._event_changed()
            return ToolResult(say="Сбой при выполнении, сэр. Причина в журнале.", ok=False)
        if ev:
            status = "done" if res.ok else "failed"
            if not self.kill.alive(gen):
                status = "cancelled"
            journal.update(self.db, ev, status, (res.log or res.say or "")[:500])
            await self._event_changed()
        return res

    async def _event_changed(self) -> None:
        await self.emit({"type": "journal"})

    async def ask_confirm(self, title: str, risk: str, event_id: int = 0, details: str = "",
                          timeout: float = 90.0) -> bool:
        """Карточка «Подтвердить / Отмена» + голосовой вопрос. Ждём ответ."""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        p = Pending(id=uuid.uuid4().hex[:10], title=title, risk=risk, future=fut, event_id=event_id)
        self.pending = p
        self.open_until = time.time() + timeout
        await self.emit({"type": "confirm", "id": p.id, "title": title, "risk": risk, "details": details})
        question = f"{title}. Подтверждаете?" if risk != "danger" else f"Внимание: {title}. Это необратимо. Подтверждаете?"
        self.speak(question)
        await self.log_line("Джарвис", question, "jarvis", confirm=p.id)
        was_busy = self.busy
        self.busy = False
        await self.set_state("idle")
        try:
            ok = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            ok = False
        finally:
            self.pending = None
            self.busy = was_busy
            await self.emit({"type": "confirm_done", "id": p.id})
        if ok:
            await self.set_state("think")
        return bool(ok)

    def resolve_confirm(self, cid: str, ok: bool) -> None:
        if self.pending and self.pending.id == cid and not self.pending.future.done():
            self.pending.future.set_result(ok)

    # ================= таймеры =================

    def add_timer(self, seconds: float, label: str, message: str) -> int:
        self.timer_seq += 1
        t = Timer(self.timer_seq, label, message, time.time() + seconds)
        t.task = asyncio.get_running_loop().create_task(self._fire(t, seconds))
        self.timers[t.id] = t
        self._spawn(self.emit({"type": "timers", "items": self.list_timers()}))
        return t.id

    async def _fire(self, t: Timer, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self.timers.pop(t.id, None)
        await self.emit({"type": "timers", "items": self.list_timers()})
        await self.emit({"type": "beep", "name": "timer"})
        await self.emit({"type": "notify", "title": "Джарвис — таймер", "body": t.message})
        await self.log_line("Система", "Таймер: " + t.label, "sys")
        self.speak(t.message)

    def clear_timers(self) -> int:
        n = len(self.timers)
        for t in self.timers.values():
            if t.task:
                t.task.cancel()
        self.timers.clear()
        self._spawn(self.emit({"type": "timers", "items": []}))
        return n

    def list_timers(self) -> list[dict]:
        now = time.time()
        return [{"id": t.id, "label": t.label, "left": max(0.0, t.at - now)} for t in self.timers.values()]
