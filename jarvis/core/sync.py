"""Один проход: прочитать выбранные чаты → сохранить новые сообщения → найти задачи.

Одинаково работает для импорта экспорта и для живого подключения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from jarvis.day.extractor import TaskExtractor
from jarvis.models import Chat, Task
from jarvis.sources.base import MessageSource
from jarvis.storage.db import Database


@dataclass
class SyncResult:
    chats: int = 0
    messages_read: int = 0
    messages_new: int = 0
    tasks_new: list[Task] = field(default_factory=list)


def sync(
    source: MessageSource,
    chats: list[Chat],
    extractor: TaskExtractor,
    db: Database,
    since: datetime | None = None,
) -> SyncResult:
    result = SyncResult(chats=len(chats))
    db.log("sync_started", source=source.name, chats=[c.title for c in chats], since=since)
    for chat in chats:
        db.upsert_chat(chat, source.name)
        messages = list(source.iter_messages([chat.id], since=since))
        result.messages_read += len(messages)
        new = db.add_messages(messages)
        result.messages_new += len(new)
        if not new:
            continue
        for task in extractor.extract(chat, new):
            if db.add_task(task):
                result.tasks_new.append(task)
                db.log("task_found", task_id=task.id, title=task.title, chat=chat.title, message_id=task.message_id)
    db.log(
        "sync_finished",
        source=source.name,
        messages_read=result.messages_read,
        messages_new=result.messages_new,
        tasks_new=len(result.tasks_new),
        llm_calls=extractor.stats.llm_calls,
        llm_errors=extractor.stats.llm_errors,
    )
    return result
