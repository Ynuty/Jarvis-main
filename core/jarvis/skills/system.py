"""
============================================================
 Навык «Система»: статус, громкость, режимы слуха, сон,
 выключение, журнал, полный экран, голос. Команды интерфейсу
 уходят событием {"type":"ui", "action": ...}.
============================================================
"""
from __future__ import annotations

import random
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from ..engines import engines
from ..security import Risk
from ..text.ru import human_duration, plural, words2num
from .base import Ctx, Reply, ToolResult, tool

S = "system"

HELP_LINES = [
    "Время и дата: «который час», «какое сегодня число».",
    "Таймеры: «поставь таймер на 10 минут», «напомни через 20 минут про плиту», «отмени таймеры».",
    "Погода: «какая погода», «погода в Казани».",
    "Справка: «что такое чёрная дыра», «кто такой Тесла».",
    "Поиск: «найди в сети курс евро» — отвечу с источниками; «найди рецепт борща» — открою браузер.",
    "Счёт: «сколько будет 47 умножить на 12», «15 процентов от 800».",
    "Сайты и программы: «открой ютуб», «открой телеграм», «запусти фотошоп» — любая установленная программа, "
    "включая приложения Microsoft Store; «сверни все окна», «переключись на хром», «обнови список программ».",
    "Заметки: «запиши купить кофе», «прочитай заметки», «удали заметки».",
    "Память: «запомни, что я не ем мясо», «что ты обо мне знаешь», «забудь про мясо».",
    "День: «добавь задачу созвон в 15:00», «что у меня сегодня», «итог дня».",
    "Заказ: «закажи из Пятёрочки молоко, хлеб и два десятка яиц», «что в корзине», «повтори прошлый заказ».",
    "Почта: «разбери почту», «что важного во входящих», «отмени последнюю сортировку».",
    "Случай: «подбрось монетку», «брось кубик», «выбери из: пицца, суши».",
    "Управление: «громче», «тише», «замолчи», «спи», «проснись», «полный экран», «статус систем», «выключись».",
    "Режим: «слушай постоянно» — отвечаю без обращения; «только по обращению» — жду слово «Джарвис».",
    "Всё остальное — просто спросите: отвечу сам.",
]


async def ui(ctx: Ctx, action: str, **kw) -> None:
    await ctx.session.emit({"type": "ui", "action": action, **kw})


# ---------- интенты ----------

def help_reply(ctx: Ctx, m, text) -> Reply:
    return Reply(
        say="Умею время и таймеры, погоду и справки, счёт, заметки и память, задачи на день, "
            "программы и окна, заказ продуктов и разбор почты. А на остальное просто отвечу. Список — в журнале.",
        log="Команды:\n• " + "\n• ".join(HELP_LINES))


def status_reply(ctx: Ctx, m, text) -> Reply:
    s = ctx.session
    up = int(time.time() - s.stats.started)
    n_t = len(s.timers)
    lat = s.stats.last_latency
    say = (f"Все системы в норме. Микрофон {'активен' if s.listening else 'выключен'}, "
           f"распознавание {'готово' if engines.stt and engines.stt.ready else 'не готово'}, "
           f"нейросеть {'на связи' if engines.llm_ok else 'недоступна'}. "
           f"Принято {s.stats.heard} {plural(s.stats.heard, 'реплика', 'реплики', 'реплик')}, "
           f"выполнено {s.stats.done} {plural(s.stats.done, 'команда', 'команды', 'команд')}. "
           f"В работе {n_t} {plural(n_t, 'таймер', 'таймера', 'таймеров')}. Время работы {human_duration(up)}.")
    log = ("Диагностика:\n"
           f"• распознавание: {engines.status['stt']}\n• голос: {engines.status['tts']}\n"
           f"• нейросеть: {engines.status['llm']}\n• режим: {s.mode}\n"
           f"• реплик: {s.stats.heard}, команд: {s.stats.done}\n• таймеров: {n_t}\n"
           f"• задержки: {lat or '—'}\n• аптайм: {human_duration(up)}")
    return Reply(say=say, log=log)


async def silence(ctx: Ctx, m, text) -> Reply:
    await ctx.session.shut_up()
    return Reply(log="Тишина.", silent=True)


async def sleep(ctx: Ctx, m, text) -> str:
    ctx.session.sleeping = True
    ctx.session.open_until = 0
    return "Перехожу в режим ожидания. Позовите по имени, сэр."


async def wake(ctx: Ctx, m, text) -> str:
    ctx.session.sleeping = False
    await ui(ctx, "listen", on=True)
    return random.choice(["Система активна, сэр.", "Я здесь. Слушаю."])


async def shutdown(ctx: Ctx, m, text) -> str:
    ctx.session.clear_timers()
    await ui(ctx, "shutdown", delay=2600)
    return "Завершаю работу. Все процессы остановлены. До встречи, сэр."


async def volume(ctx: Ctx, m, text) -> str:
    nums = re.findall(r"\d+", words2num(text))
    if nums:
        v = min(100, int(nums[0])) / 100
    else:
        louder = bool(re.search(r"(громче|погромче)", text))
        v = ctx.session.volume + (0.2 if louder else -0.2)
    r = await ctx.call("system.volume", {"level": max(0.0, min(1.0, v))})
    return r.say


def repeat(ctx: Ctx, m, text) -> Reply:
    last = ctx.session.last_reply
    return Reply(say=last, log="Повтор.") if last else Reply(say="Мне пока нечего повторять, сэр.")


async def set_mode(ctx: Ctx, mode: str) -> str:
    r = await ctx.call("system.mode", {"mode": mode})
    return r.say


async def fullscreen(ctx: Ctx, m, text) -> str:
    await ui(ctx, "fullscreen")
    return "Разворачиваю интерфейс."


async def clear_log(ctx: Ctx, m, text) -> str:
    await ui(ctx, "clear_log")
    return "Журнал очищен, сэр."


async def next_voice(ctx: Ctx, m, text) -> str:
    from ..voice.tts import PIPER_VOICES
    names = list(PIPER_VOICES)
    cur = ctx.setting("tts_voice")
    nxt = names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]
    from ..voice.tts import piper_paths
    if not piper_paths(nxt)[0].exists():
        return "Другой голос не скачан, сэр. Загрузить можно в настройках."
    ctx.session.settings.set("tts_voice", nxt)
    engines.load_voice(ctx.session.settings.all())
    return f"Голос переключён: {nxt.split('-')[1]}."


# ---------- инструменты ----------

class VolumeArgs(BaseModel):
    level: float = Field(ge=0, le=1, description="громкость 0..1")


@tool("system.volume", skill=S, title="Громкость голоса", risk=Risk.LOCAL, args=VolumeArgs,
      description="изменить громкость голоса Джарвиса, level от 0 до 1",
      summary=lambda a: f"Громкость {round(a.level * 100)}%")
async def t_volume(ctx: Ctx, a: VolumeArgs) -> ToolResult:
    ctx.session.volume = a.level
    await ui(ctx, "volume", level=a.level)
    return ToolResult(say=f"Громкость {round(a.level * 100)} процентов.")


class ModeArgs(BaseModel):
    mode: Literal["wake", "open", "ptt"]


@tool("system.mode", skill=S, title="Режим слуха", risk=Risk.LOCAL, args=ModeArgs,
      description="режим прослушивания: wake — по слову «Джарвис», open — постоянно, ptt — по кнопке")
async def t_mode(ctx: Ctx, a: ModeArgs) -> ToolResult:
    s = ctx.session
    s.mode = a.mode
    s.settings.set("listen_mode", a.mode)
    await s.emit({"type": "status", **s.status_payload()})
    return ToolResult(say={
        "open": "Отвечаю на любую фразу. Имя называть не нужно.",
        "wake": "Буду отзываться только на «Джарвис».",
        "ptt": "Слушаю только по кнопке, сэр.",
    }[a.mode])
