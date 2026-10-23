"""
============================================================
 Навык «День» — свой календарь вместо внешнего: задачи со временем,
 отметки «сделано», вечерний итог. Задачи — точки на кольце суток
 вокруг реактора, шторка «День» (Ctrl+D) показывает план и журнал
 «Сделано Джарвисом».
============================================================
"""
from __future__ import annotations

import datetime as dt
import re
import time

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from .. import journal
from ..security import Risk
from ..text.ru import DAYS, MONTHS, plural, words2num
from .base import Ctx, Reply, ToolResult, tool

S = "day"

_WD = {"понедельник": 0, "вторник": 1, "среду": 2, "среда": 2, "четверг": 3, "пятницу": 4, "пятница": 4,
       "субботу": 5, "суббота": 5, "воскресенье": 6}


def parse_when(text: str, now: dt.datetime | None = None) -> tuple[str, float | None]:
    """
    «созвон с командой в 15:00» → («созвон с командой», сегодня 15:00)
    «завтра в 9 утра позвонить маме» → («позвонить маме», завтра 09:00)
    «через 2 часа выпить таблетку»   → («выпить таблетку», now + 2ч)
    """
    now = now or dt.datetime.now()
    s = words2num(text)
    day = now.date()
    when_t: tuple[int, int] | None = None
    rel: dt.timedelta | None = None

    def cut(pattern: str) -> re.Match | None:
        nonlocal s
        m = re.search(pattern, s)
        if m:
            s = (s[:m.start()] + " " + s[m.end():]).strip()
        return m

    if cut(r"\bпослезавтра\b"):
        day = day + dt.timedelta(days=2)
    elif cut(r"\bзавтра\b"):
        day = day + dt.timedelta(days=1)
    elif cut(r"\bсегодня\b"):
        pass
    elif m := cut(r"\bв(?:о)?\s+(понедельник|вторник|среду|среда|четверг|пятницу|пятница|субботу|суббота|воскресенье)\b"):
        delta = (_WD[m.group(1)] - now.weekday()) % 7 or 7
        day = day + dt.timedelta(days=delta)

    if m := cut(r"\bчерез\s+(\d+(?:[.,]\d+)?)?\s*(минут\w*|час\w*|полчаса)"):
        n = float((m.group(1) or "1").replace(",", "."))
        unit = m.group(2)
        rel = dt.timedelta(minutes=30) if unit == "полчаса" else \
            dt.timedelta(minutes=n) if unit.startswith("мин") else dt.timedelta(hours=n)
    elif m := cut(r"\bв\s+(\d{1,2})[:.](\d{2})\b"):
        when_t = (int(m.group(1)), int(m.group(2)))
    elif m := cut(r"\bв\s+(\d{1,2})\s*(?:час\w*)?\s*(утра|дня|вечера|ночи)?(?:\s+(\d{1,2})\s*минут\w*)?\b"):
        h = int(m.group(1))
        part = m.group(2)
        if part in ("дня", "вечера") and h < 12:
            h += 12
        if part == "ночи" and h == 12:
            h = 0
        when_t = (h % 24, int(m.group(3) or 0))
    elif m := cut(r"\b(утром|днем|вечером)\b"):
        when_t = {"утром": (9, 0), "днем": (14, 0), "вечером": (19, 0)}[m.group(1)]

    title = re.sub(r"\s+", " ", s).strip(" ,.-")
    title = re.sub(r"^(что|чтобы|надо|нужно)\s+", "", title)
    if rel is not None:
        return title, (now + rel).timestamp()
    if when_t is not None:
        return title, dt.datetime.combine(day, dt.time(*when_t)).timestamp()
    if day != now.date():
        return title, dt.datetime.combine(day, dt.time(9, 0)).timestamp()
    return title, None


def day_bounds(ts: float | None = None) -> tuple[float, float]:
    d = dt.datetime.fromtimestamp(ts or time.time()).date()
    start = dt.datetime.combine(d, dt.time()).timestamp()
    return start, start + 86400


def tasks_for_day(db, profile_id: int, ts: float | None = None) -> list[dict]:
    a, b = day_bounds(ts)
    rows = db.q("SELECT * FROM tasks WHERE profile_id=? AND status!='cancelled' AND "
                "((due_at>=? AND due_at<?) OR (due_at IS NULL AND (status='open' OR (done_at>=? AND done_at<?)))) "
                "ORDER BY due_at IS NULL, due_at, id", (profile_id, a, b, a, b))
    return [dict(r) for r in rows]


def hhmm(ts: float | None) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else ""


def _when_words(ts: float | None) -> str:
    if not ts:
        return ""
    d = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    if d.date() == today:
        prefix = "сегодня"
    elif d.date() == today + dt.timedelta(days=1):
        prefix = "завтра"
    else:
        prefix = f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"
    return f"{prefix} в {d:%H:%M}"


async def _changed(ctx: Ctx) -> None:
    await ctx.session.emit({"type": "day"})


class TaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    when: str = Field("", description="когда, словами: «завтра в 9», «в 15:30», «через 2 часа»; пусто — без времени")
    due_at: float | None = Field(None, description="служебное: unix-время, если уже разобрано")

    def model_post_init(self, _ctx) -> None:
        if self.due_at is None and self.when:
            self.due_at = parse_when(self.when)[1]


@tool("task.add", skill=S, title="Добавить задачу", risk=Risk.LOCAL, args=TaskArgs,
      description="добавить задачу в план дня",
      summary=lambda a: f"Добавил задачу «{a.title}»" + (f" на {_when_words(a.due_at)}" if a.due_at else ""))
async def t_add(ctx: Ctx, a: TaskArgs) -> ToolResult:
    by = "assistant" if ctx.origin == "llm" else "user"
    ctx.db.run("INSERT INTO tasks(profile_id, title, due_at, created_by, created_at) VALUES (?,?,?,?,?)",
               (ctx.profile_id, a.title, a.due_at, by, time.time()))
    await _changed(ctx)
    return ToolResult(say=f"Добавил: {a.title}" + (f", {_when_words(a.due_at)}." if a.due_at else "."))


class TaskRef(BaseModel):
    title: str = Field(min_length=1, description="название задачи или его часть")


def _find_task(ctx: Ctx, title: str, status: str = "open") -> dict | None:
    rows = [dict(r) for r in ctx.db.q("SELECT * FROM tasks WHERE profile_id=? AND status=?", (ctx.profile_id, status))]
    if not rows:
        return None
    best = process.extractOne(title, {r["id"]: r["title"] for r in rows}, scorer=fuzz.WRatio)
    if not best or best[1] < 60:
        return None
    return next(r for r in rows if r["id"] == best[2])


@tool("task.done", skill=S, title="Отметить задачу", risk=Risk.LOCAL, args=TaskRef,
      description="отметить задачу выполненной", summary=lambda a: f"Отметил выполненной «{a.title}»")
async def t_done(ctx: Ctx, a: TaskRef) -> ToolResult:
    t = _find_task(ctx, a.title)
    if not t:
        return ToolResult(say="Не нашёл такой задачи, сэр.", ok=False)
    ctx.db.run("UPDATE tasks SET status='done', done_at=? WHERE id=?", (time.time(), t["id"]))
    await _changed(ctx)
    return ToolResult(say=f"Отметил: {t['title']}. Хорошая работа, сэр.")


@tool("task.remove", skill=S, title="Удалить задачу", risk=Risk.LOCAL, args=TaskRef,
      description="убрать задачу из плана", summary=lambda a: f"Убрал задачу «{a.title}»")
async def t_remove(ctx: Ctx, a: TaskRef) -> ToolResult:
    t = _find_task(ctx, a.title)
    if not t:
        return ToolResult(say="Не нашёл такой задачи, сэр.", ok=False)
    ctx.db.run("UPDATE tasks SET status='cancelled' WHERE id=?", (t["id"],))
    await _changed(ctx)
    return ToolResult(say=f"Убрал из плана: {t['title']}.")


@tool("task.list", skill=S, title="План на день", risk=Risk.READ, description="задачи на сегодня")
def t_list(ctx: Ctx) -> ToolResult:
    ts = tasks_for_day(ctx.db, ctx.profile_id)
    open_ = [t for t in ts if t["status"] == "open"]
    done = [t for t in ts if t["status"] == "done"]
    if not ts:
        return ToolResult(say="На сегодня задач нет, сэр. День свободен.")
    head = f"На сегодня {len(ts)} {plural(len(ts), 'задача', 'задачи', 'задач')}, сделано {len(done)}."
    rest = " ".join(f"{(hhmm(t['due_at']) + ' — ') if t['due_at'] else ''}{t['title']}." for t in open_[:5])
    lines = [f"{'✓' if t['status'] == 'done' else '•'} {hhmm(t['due_at']) or '—'} {t['title']}" for t in ts]
    return ToolResult(say=(head + (" Осталось: " + rest if open_ else "")).strip(), log="План:\n" + "\n".join(lines))


def summary_text(ctx: Ctx) -> tuple[str, str]:
    a, b = day_bounds()
    ts = tasks_for_day(ctx.db, ctx.profile_id)
    done = [t for t in ts if t["status"] == "done"]
    open_ = [t for t in ts if t["status"] == "open"]
    evs = [e for e in journal.recent(ctx.db, ctx.profile_id, 200, since=a) if e["status"] == "done"]
    say = (f"Итог дня: задач выполнено {len(done)} из {len(ts)}. "
           f"Я сделал {len(evs)} {plural(len(evs), 'действие', 'действия', 'действий')} по вашим просьбам.")
    if open_:
        say += " Не успели: " + ", ".join(t["title"] for t in open_[:3]) + ". Перенести на завтра?"
    log = say + "\n\nСделано Джарвисом:\n" + "\n".join(
        f"{dt.datetime.fromtimestamp(e['ts']):%H:%M} {e['summary']}" for e in reversed(evs[:30]))
    return say, log


@tool("day.summary", skill=S, title="Итог дня", risk=Risk.READ, description="вечерний итог: что сделано за день")
def t_summary(ctx: Ctx) -> ToolResult:
    say, log = summary_text(ctx)
    return ToolResult(say=say, log=log)


@tool("task.move_open_to_tomorrow", skill=S, title="Перенести несделанное на завтра", risk=Risk.LOCAL,
      description="перенести невыполненные задачи сегодняшнего дня на завтра")
async def t_move(ctx: Ctx) -> ToolResult:
    ts = [t for t in tasks_for_day(ctx.db, ctx.profile_id) if t["status"] == "open"]
    for t in ts:
        base = t["due_at"] or (day_bounds()[0] + 9 * 3600)
        ctx.db.run("UPDATE tasks SET due_at=? WHERE id=?", (base + 86400, t["id"]))
    await _changed(ctx)
    n = len(ts)
    return ToolResult(say=f"Перенёс {n} {plural(n, 'задачу', 'задачи', 'задач')} на завтра." if n else "Переносить нечего, сэр.")


# ---------- интенты ----------

async def add(ctx: Ctx, m, text):
    title, due = parse_when(m.group(2))
    if not title:
        return "Как назвать задачу, сэр?"
    return (await ctx.call("task.add", {"title": title, "due_at": due})).say


async def done(ctx: Ctx, m, text):
    title = re.sub(r"\s*(как\s+)?(выполненн\w*|сделанн\w*|готов\w*)$", "", m.group(2)).strip()
    title = re.sub(r"^(задачу|задача)\s+", "", title)
    return (await ctx.call("task.done", {"title": title})).say


async def remove(ctx: Ctx, m, text):
    return (await ctx.call("task.remove", {"title": m.group(2)})).say


async def plan(ctx: Ctx, m, text):
    r = await ctx.call("task.list")
    return Reply(say=r.say, log=r.log)


async def summary(ctx: Ctx, m, text):
    r = await ctx.call("day.summary")
    return Reply(say=r.say, log=r.log)


async def move_tomorrow(ctx: Ctx, m, text):
    return (await ctx.call("task.move_open_to_tomorrow")).say


async def open_sheet(ctx: Ctx, m, text):
    await ctx.session.emit({"type": "ui", "action": "day_sheet"})
    return Reply(say="", log="Открываю шторку «День».", silent=True)
