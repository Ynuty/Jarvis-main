"""Общий интерфейс источника сообщений.

Извлечение задач и список дел не знают, откуда пришли сообщения:
из файла экспорта или из живого подключения к аккаунту.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Protocol

from jarvis.models import Chat, Message


class MessageSource(Protocol):
    name: str

    def list_chats(self) -> list[Chat]:
        """Все чаты, которые источник может прочитать."""
        ...

    def iter_messages(
        self, chat_ids: Iterable[str], since: datetime | None = None
    ) -> Iterator[Message]:
        """Сообщения только из выбранных чатов, от старых к новым."""
        ...


def resolve_chats(chats: list[Chat], selectors: Iterable[str]) -> list[Chat]:
    """Находит чаты по id ("tg:123" или "123") или по точному названию.

    Пользователь сам выбирает, какие чаты читать: без выбора не читается ничего.
    """
    found: list[Chat] = []
    for raw in selectors:
        sel = raw.strip()
        match = None
        for chat in chats:
            if sel in (chat.id, chat.id.removeprefix("tg:")) or sel.casefold() == chat.title.casefold():
                match = chat
                break
        if match is None:
            raise LookupError(f"Чат не найден: {raw!r}")
        if match not in found:
            found.append(match)
    return found
