"""
============================================================
 TTS — синтез речи офлайн. Движки:
   piper  — по умолчанию: ONNX, лёгкий, русские голоса denis/dmitri/irina/ruslan;
   silero — если установлен torch (лучше ударения), подключается в настройках;
   client — запасной: текст уходит в интерфейс, говорит Web Speech API.
 Озвучка идёт по предложениям: SentenceSplitter отдаёт готовые фразы
 из потока токенов LLM, и голос начинается, не дожидаясь конца ответа.
============================================================
"""
from __future__ import annotations

import io
import logging
import re
import threading
import wave
from pathlib import Path

from .. import config

log = logging.getLogger("jarvis.tts")

PIPER_VOICES = {
    "ru_RU-denis-medium": "ru/ru_RU/denis/medium",
    "ru_RU-dmitri-medium": "ru/ru_RU/dmitri/medium",
    "ru_RU-irina-medium": "ru/ru_RU/irina/medium",
    "ru_RU-ruslan-medium": "ru/ru_RU/ruslan/medium",
}


def piper_paths(voice: str) -> tuple[Path, Path]:
    base = config.MODELS / "piper" / voice
    return base.with_suffix(".onnx"), base.with_suffix(".onnx.json")


class TTS:
    def __init__(self, engine: str = "piper", voice: str = "ru_RU-denis-medium", rate: float = 1.0) -> None:
        self.engine_pref = engine
        self.voice_name = voice
        self.rate = rate
        self.engine = "client"
        self.voice = None
        self.lock = threading.Lock()
        self.error = ""

    def load(self) -> bool:
        if self.engine_pref == "piper" and self._load_piper():
            return True
        if self.engine_pref == "silero" and self._load_silero():
            return True
        self.engine = "client"
        return False

    def _load_piper(self) -> bool:
        onnx, cfg = piper_paths(self.voice_name)
        if not onnx.exists():
            self.error = f"нет файла голоса {onnx.name} — скачайте в мастере первого запуска"
            return False
        try:
            from piper import PiperVoice
            self.voice = PiperVoice.load(str(onnx), config_path=str(cfg))
            self.engine = "piper"
            return True
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.warning("piper не поднялся: %s", e)
            return False

    def _load_silero(self) -> bool:
        try:
            import torch  # noqa: F401 — опциональная зависимость
            model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru", speaker="v4_ru",
                                      trust_repo=True)
            self.voice = model
            self.engine = "silero"
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"silero: {e}"
            return False

    @property
    def ready(self) -> bool:
        return self.engine != "client"

    def synth(self, text: str) -> bytes:
        """Фраза → WAV (PCM16 mono). Пусто — если движка нет."""
        text = speakable(text)
        if not text or not self.ready:
            return b""
        with self.lock:
            if self.engine == "piper":
                from piper import SynthesisConfig
                cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, self.rate)))
                chunks = list(self.voice.synthesize(text, syn_config=cfg))
                if not chunks:
                    return b""
                pcm = b"".join(c.audio_int16_bytes for c in chunks)
                return _wav(pcm, chunks[0].sample_rate)
            if self.engine == "silero":
                import numpy as np
                audio = self.voice.apply_tts(text=text, speaker="aidar", sample_rate=24000,
                                             put_accent=True, put_yo=True)
                pcm = (np.clip(audio.numpy(), -1, 1) * 32767).astype("<i2").tobytes()
                return _wav(pcm, 24000)
        return b""


def _wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


_MD = re.compile(r"[*_`#>\[\]]|https?://\S+")


def speakable(text: str) -> str:
    """Убирает разметку, ссылки и символы, которые синтез читает вслух."""
    t = _MD.sub(" ", text or "")
    t = t.replace("°", " градусов ").replace("%", " процентов").replace("№", "номер ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


class SentenceSplitter:
    """Копит поток символов, отдаёт законченные предложения."""

    END = re.compile(r"(.+?[.!?…;:])(\s+|$)", re.S)

    def __init__(self, min_len: int = 12) -> None:
        self.buf = ""
        self.min_len = min_len

    def push(self, piece: str) -> list[str]:
        self.buf += piece
        out = []
        while True:
            m = self.END.match(self.buf)
            if not m or not m.group(2):
                break
            sent = m.group(1).strip()
            # короткие обрывки («Да.», «Сэр.») приклеиваем к следующей фразе
            if len(sent) < self.min_len and len(self.buf) < 200:
                nxt = self.END.match(self.buf, m.end())
                if not nxt or not nxt.group(2):
                    break
                sent = (sent + " " + nxt.group(1).strip()).strip()
                self.buf = self.buf[nxt.end():]
            else:
                self.buf = self.buf[m.end():]
            out.append(sent)
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []
