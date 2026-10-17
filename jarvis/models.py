"""Общие модели данных: чат, сообщение, задача."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Кому адресована задача
ASSIGNEE_ME = "me"          # пользователю
ASSIGNEE_OTHER = "other"    # кому-то другому — в список не попадает
ASSIGNEE_UNCLEAR = "unclear"  # непонятно — показываем, но с пометкой

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"


@dataclass(frozen=True)
class Chat:
    id: str      # "tg:<id>" — уникален в пределах источника
    title: str
    kind: str    # private / group / channel / saved / bot / unknown


@dataclass(frozen=True)
class Message:
    chat_id: str
    message_id: int
    date: datetime          # локальное время, без часового пояса
    author: str | None
    author_id: str | None
    text: str
    reply_to: int | None = None
    is_outgoing: bool = False   # отправлено самим пользователем


@dataclass
class Task:
    title: str
    chat_id: str
    message_id: int
    source_text: str
    requested_by: str | None = None
    due_at: datetime | None = None
    due_text: str | None = None
    assignee: str = ASSIGNEE_ME
    confidence: float = 0.5
    status: str = STATUS_OPEN
    id: int | None = None
    created_at: datetime | None = None
