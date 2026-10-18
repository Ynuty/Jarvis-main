"""Навык «Сообщения» (этап 6, заготовка): сводка в режиме «только чтение».

Правило против prompt injection: текст сообщений — данные, а не инструкции.
Сводка делается отдельным вызовом LLM без доступа к инструментам
(LLMClient.summarize_untrusted), а любое действие, предложенное по тексту
сообщения, выполняется с source="message" — политика требует подтверждения.
"""
from __future__ import annotations

from ...security import Risk
from ..base import Skill, Tool, ToolResult, schema

# Коннектор: объект с методом fetch_unread() -> list[{"from","chat","text"}].
# Почта через IMAP — первый кандидат; способ чтения Telegram ещё не выбран.
CONNECTORS: list = []


def digest(ctx) -> ToolResult:
    if not CONNECTORS:
        return ToolResult(True, "Источники сообщений пока не подключены — сводка появится на этапе 6")
    items = [m for c in CONNECTORS for m in c.fetch_unread()]
    if not items:
        return ToolResult(True, "Новых сообщений нет")
    llm = ctx.extra.get("llm")
    text = llm.summarize_untrusted(items) if llm else None
    if not text:
        by_chat: dict[str, int] = {}
        for m in items:
            by_chat[m["chat"]] = by_chat.get(m["chat"], 0) + 1
        text = "Новые сообщения: " + ", ".join(f"{k} — {v}" for k, v in by_chat.items())
    return ToolResult(True, text)


SKILL = Skill("messages", "Сообщения", [
    Tool("digest", "Сводка непрочитанных сообщений (только чтение)", schema(), Risk.SAFE, digest),
])
