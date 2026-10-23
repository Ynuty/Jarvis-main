"""Навык «Заметки»: быстрые записи в профиль (SQLite)."""
from __future__ import annotations

import time

from pydantic import BaseModel, Field

from ..security import Risk
from ..text.ru import plural
from .base import Ctx, Reply, ToolResult, tool

S = "notes"


class NoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@tool("note.add", skill=S, title="Заметка", risk=Risk.LOCAL, args=NoteArgs,
      description="записать заметку", summary=lambda a: f"Записал заметку «{a.text[:60]}»")
def t_add(ctx: Ctx, a: NoteArgs) -> ToolResult:
    ctx.db.run("INSERT INTO notes(profile_id, text, at) VALUES (?,?,?)", (ctx.profile_id, a.text.strip(), time.time()))
    return ToolResult(say=f"Записал: {a.text.strip()}.")


def all_notes(ctx: Ctx) -> list[str]:
    return [r["text"] for r in ctx.db.q("SELECT text FROM notes WHERE profile_id=? ORDER BY id", (ctx.profile_id,))]


@tool("note.list", skill=S, title="Заметки", risk=Risk.READ, description="прочитать заметки")
def t_list(ctx: Ctx) -> ToolResult:
    notes = all_notes(ctx)
    if not notes:
        return ToolResult(say="Заметок нет, сэр.")
    n = len(notes)
    return ToolResult(say=f"{n} {plural(n, 'заметка', 'заметки', 'заметок')}. "
                          + ". ".join(f"{i + 1}. {t}" for i, t in enumerate(notes)),
                      log="Заметки:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(notes)))


@tool("note.clear", skill=S, title="Удалить все заметки", risk=Risk.LOCAL,
      description="удалить все заметки")
def t_clear(ctx: Ctx) -> ToolResult:
    ctx.db.run("DELETE FROM notes WHERE profile_id=?", (ctx.profile_id,))
    return ToolResult(say="Заметки удалены, сэр.")


async def add(ctx: Ctx, m, text):
    return (await ctx.call("note.add", {"text": m.group(2).strip()})).say


async def read(ctx: Ctx, m, text):
    r = await ctx.call("note.list")
    return Reply(say=r.say, log=r.log)


async def clear(ctx: Ctx, m, text):
    return (await ctx.call("note.clear")).say
