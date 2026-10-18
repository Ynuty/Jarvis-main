"""Навык «День»: свой календарь внутри приложения — задачи, их время
и всё, что ассистент сделал за день (журнал)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ...security import Risk
from ..base import Skill, Tool, ToolResult, schema


def _due(time: str | None, day_offset: int) -> datetime | None:
    if not time and not day_offset:
        return None
    d = date.today() + timedelta(days=day_offset)
    if not time:
        return datetime(d.year, d.month, d.day, 9, 0)
    hh, _, mm = time.partition(":")
    return datetime(d.year, d.month, d.day, int(hh) % 24, int(mm or 0) % 60)


def add_task(ctx, title: str, time: str | None = None, day_offset: int = 0) -> ToolResult:
    title = title.strip().rstrip(".")
    if not title:
        return ToolResult(False, "Не услышал название задачи")
    title = title[0].upper() + title[1:]
    due = _due(time, day_offset)
    tid = ctx.storage.add_task(title, due, created_by="assistant" if ctx.extra.get("source") != "user" else "user")
    when = f" на {due:%H:%M}" if due and time else ""
    if day_offset == 1:
        when = " на завтра" + when
    return ToolResult(True, f"Добавил задачу «{title}»{when}", task_id=tid,
                      undo={"tool": "day.delete_task", "args": {"task_id": tid}}, ui={"refresh_day": True})


def delete_task(ctx, task_id: int) -> ToolResult:
    task = ctx.storage.get_task(task_id)
    if not task:
        return ToolResult(False, "Такой задачи уже нет")
    ctx.storage.delete_task(task_id)
    return ToolResult(True, f"Удалил задачу «{task['title']}»", ui={"refresh_day": True})


def complete_task(ctx, title: str | None = None, task_id: int | None = None) -> ToolResult:
    task = ctx.storage.get_task(task_id) if task_id else ctx.storage.find_open_task(title or "", date.today())
    if not task:
        return ToolResult(False, f"Не нашёл задачу «{title}» в плане на сегодня")
    ctx.storage.set_task_status(task["id"], "done")
    return ToolResult(True, f"Отметил выполненной «{task['title']}»", task_id=task["id"],
                      undo={"tool": "day.reopen_task", "args": {"task_id": task["id"]}},
                      ui={"refresh_day": True})


def reopen_task(ctx, task_id: int) -> ToolResult:
    task = ctx.storage.get_task(task_id)
    if not task:
        return ToolResult(False, "Такой задачи уже нет")
    ctx.storage.set_task_status(task_id, "open")
    return ToolResult(True, f"Вернул в план «{task['title']}»", ui={"refresh_day": True})


def list_today(ctx) -> ToolResult:
    tasks = ctx.storage.tasks_for_day(date.today())
    open_ = [t for t in tasks if t["status"] != "done"]
    if not tasks:
        return ToolResult(True, "На сегодня задач нет", data=tasks, ui={"open_day": True})
    parts = [(t["due_at"][11:16] + " " if t["due_at"] else "") + t["title"] for t in open_[:5]]
    head = f"Сделано {len(tasks) - len(open_)} из {len(tasks)}."
    tail = " Осталось: " + "; ".join(parts) if parts else " Всё выполнено!"
    return ToolResult(True, head + tail, data=tasks, ui={"open_day": True})


def summary(ctx) -> ToolResult:
    """Вечерний итог: задачи + журнал действий ассистента."""
    today = date.today()
    tasks = ctx.storage.tasks_for_day(today)
    done = [t for t in tasks if t["status"] == "done"]
    events = [e for e in ctx.storage.events_for_day(today, "done") if e["skill"] not in ("system",)]
    lines = [f"Итог дня: выполнено задач {len(done)} из {len(tasks)}, Джарвис сделал действий: {len(events)}."]
    left = [t["title"] for t in tasks if t["status"] != "done"]
    if left:
        lines.append("Перенести на завтра: " + ", ".join(left[:5]) + ".")
    return ToolResult(True, " ".join(lines), ui={"open_day": True})


def show(ctx) -> ToolResult:
    return ToolResult(True, "Открыл шторку «День»", ui={"open_day": True})


SKILL = Skill("day", "День", [
    Tool("add_task", "Добавить задачу в план",
         schema({"title": {"type": "string"},
                 "time": {"type": "string", "description": "ЧЧ:ММ, если названо время"},
                 "day_offset": {"type": "integer", "description": "0 — сегодня, 1 — завтра"}}, ["title"]),
         Risk.LOW, add_task),
    Tool("complete_task", "Отметить задачу выполненной",
         schema({"title": {"type": "string"}, "task_id": {"type": "integer"}}), Risk.LOW, complete_task),
    Tool("list_today", "Рассказать план на сегодня", schema(), Risk.SAFE, list_today),
    Tool("summary", "Подвести итог дня", schema(), Risk.SAFE, summary),
    Tool("show", "Открыть шторку «День»", schema(), Risk.SAFE, show),
    # Служебные — только для отката; LLM и роутер их не вызывают.
    Tool("delete_task", "Удалить задачу", schema({"task_id": {"type": "integer"}}, ["task_id"]),
         Risk.LOW, delete_task, hidden=True),
    Tool("reopen_task", "Вернуть задачу в план", schema({"task_id": {"type": "integer"}}, ["task_id"]),
         Risk.LOW, reopen_task, hidden=True),
])
