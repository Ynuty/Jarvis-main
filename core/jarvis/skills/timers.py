"""Навык «Таймеры»: таймеры и напоминания (живут в сессии ядра, уведомление — в трей)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..security import Risk
from ..text.ru import human_duration, parse_duration, plural
from .base import Ctx, ToolResult, tool

S = "timers"


class TimerArgs(BaseModel):
    seconds: int = Field(gt=0, le=7 * 24 * 3600, description="длительность в секундах")
    about: str = Field("", description="о чём напомнить, можно пусто")


@tool("timer.set", skill=S, title="Таймер", risk=Risk.LOCAL, args=TimerArgs,
      description="поставить таймер или напоминание через seconds секунд",
      summary=lambda a: f"Таймер на {human_duration(a.seconds)}" + (f": {a.about}" if a.about else ""))
def t_set(ctx: Ctx, a: TimerArgs) -> ToolResult:
    label = a.about or human_duration(a.seconds)
    msg = f"Напоминаю, сэр: {a.about}." if a.about else "Время вышло, сэр."
    ctx.session.add_timer(a.seconds, label, msg)
    if a.about:
        return ToolResult(say=f"Напомню через {human_duration(a.seconds)}: {a.about}.")
    return ToolResult(say=f"Таймер на {human_duration(a.seconds)} запущен.")


@tool("timer.cancel_all", skill=S, title="Отменить таймеры", risk=Risk.LOCAL,
      description="отменить все таймеры и напоминания")
def t_cancel(ctx: Ctx) -> ToolResult:
    n = ctx.session.clear_timers()
    return ToolResult(say=f"Отменил {n} {plural(n, 'таймер', 'таймера', 'таймеров')}, сэр." if n
                      else "Активных таймеров нет, сэр.")


@tool("timer.list", skill=S, title="Список таймеров", risk=Risk.READ, description="какие таймеры идут")
def t_list(ctx: Ctx) -> ToolResult:
    items = ctx.session.list_timers()
    if not items:
        return ToolResult(say="Активных таймеров нет, сэр.")
    return ToolResult(say="В работе: " + "; ".join(
        f"{t['label']} — осталось {human_duration(round(t['left']))}" for t in items) + ".")


# ---------- интенты ----------

async def reminder(ctx: Ctx, m, text):
    rest = m.group(2)
    sec = parse_duration(rest)
    if not sec:
        return "Не разобрал интервал, сэр. Скажите «напомни через 15 минут выключить плиту»."
    about = re.sub(r"^[^а-я\d]*", "", rest)
    about = re.sub(r"(\d+|[а-я]+)?\s*(с половиной\s+)?(секунд\w*|сек|минут\w*|мин|час\w*|ч)\b|полчаса|полминуты",
                   "", about, count=1)
    about = re.sub(r"^\s*(про|о|об|что|чтобы|надо)\s+", "", about).strip()
    r = await ctx.call("timer.set", {"seconds": sec, "about": about})
    return r.say


async def timer(ctx: Ctx, m, text):
    sec = parse_duration(text)
    if not sec:
        return "На сколько ставить, сэр? Например: «таймер на 7 минут»."
    r = await ctx.call("timer.set", {"seconds": sec})
    return r.say
