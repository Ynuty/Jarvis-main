"""
============================================================
 Роутер правил: быстрые интенты без LLM, за миллисекунды.
 INTENTS — упорядоченный список, побеждает первое совпадение.
 Широкие шаблоны (open, search, timer, note-add) стоят ниже узких.
 Всё, что правила не узнали, уходит в LLM.
============================================================
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable

from ..skills.base import Ctx, Reply
from ..text.ru import words2num


@dataclass
class Intent:
    id: str
    re: re.Pattern
    run: Callable[..., Any]
    guard: Callable[[str], bool] | None = None
    nums: bool = False          # сопоставлять с текстом, где числительные уже заменены цифрами


def intent(id: str, pattern: str, run: Callable[..., Any], guard: Callable[[str], bool] | None = None,
           nums: bool = False) -> Intent:
    return Intent(id=id, re=re.compile(pattern), run=run, guard=guard, nums=nums)


def find(text: str) -> tuple[Intent, re.Match, str] | None:
    """Только сопоставление — для тестов и отладки. Возвращает (интент, совпадение, текст)."""
    from .rules import INTENTS
    digits = words2num(text)
    for it in INTENTS:
        if it.guard and not it.guard(text):
            continue
        src = digits if it.nums else text
        m = it.re.search(src)
        if m:
            return it, m, src
    return None


async def match(ctx: Ctx, text: str) -> Reply | None:
    hit = find(text)
    if not hit:
        return None
    it, m, src = hit
    out = it.run(ctx, m, src)
    if inspect.isawaitable(out):
        out = await out
    if out is None:
        return None          # обработчик передумал — пусть решает LLM
    return Reply.of(out, it.id)
