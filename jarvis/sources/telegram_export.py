"""Источник: экспорт переписки из Telegram Desktop в формате JSON.

Тестовый режим MVP. Вход в аккаунт не нужен: пользователь сам выгружает
выбранные чаты (Telegram Desktop → Настройки → Продвинутые настройки →
Экспорт данных, формат «Машиночитаемый JSON») и указывает файл result.json.

Поддерживаются оба вида выгрузки:
- экспорт одного чата (в корне есть "messages");
- полный экспорт аккаунта (в корне есть "chats" → "list").
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from jarvis.models import Chat, Message

_KIND = {
    "personal_chat": "private",
    "bot_chat": "bot",
    "saved_messages": "saved",
    "private_group": "group",
    "private_supergroup": "group",
    "public_supergroup": "group",
    "private_channel": "channel",
    "public_channel": "channel",
}


def flatten_text(raw) -> str:
    """В экспорте text — строка или список строк и объектов {"type", "text"}."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    for item in raw:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("text", "")))
    return "".join(parts)


class TelegramExportSource:
    name = "telegram_export"

    def __init__(self, path: str | Path, me: str | None = None):
        """me — как пользователь подписан в Telegram (имя или id вида user123).

        В полном экспорте пользователь определяется автоматически,
        в экспорте одного чата его нужно указать, чтобы отличать свои сообщения.
        """
        self.path = Path(path)
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)

        self._self_id: str | None = None
        personal = data.get("personal_information") or {}
        if personal.get("user_id"):
            self._self_id = f"user{personal['user_id']}"
        self._me = me.strip().casefold() if me else None

        if "messages" in data:
            raw_chats = [data]
        elif isinstance(data.get("chats"), dict):
            raw_chats = list(data["chats"].get("list", []))
            left = data.get("left_chats")
            if isinstance(left, dict):
                raw_chats += list(left.get("list", []))
        else:
            raise ValueError(
                "Файл не похож на экспорт Telegram Desktop в JSON: нет ни \"messages\", ни \"chats\"."
            )
        self._raw = {f"tg:{c.get('id')}": c for c in raw_chats if c.get("id") is not None}

    def list_chats(self) -> list[Chat]:
        chats = []
        for chat_id, raw in self._raw.items():
            kind = _KIND.get(raw.get("type", ""), "unknown")
            title = raw.get("name") or ("Избранное" if kind == "saved" else "Без названия")
            chats.append(Chat(id=chat_id, title=title, kind=kind))
        return chats

    def message_count(self, chat_id: str) -> int:
        raw = self._raw.get(chat_id, {})
        return sum(1 for m in raw.get("messages", []) if m.get("type") == "message")

    def _is_outgoing(self, msg: dict) -> bool:
        from_id = msg.get("from_id")
        if self._self_id and from_id == self._self_id:
            return True
        if self._me:
            if from_id and from_id.casefold() == self._me:
                return True
            author = msg.get("from")
            if author and author.strip().casefold() == self._me:
                return True
        return False

    def iter_messages(
        self, chat_ids: Iterable[str], since: datetime | None = None
    ) -> Iterator[Message]:
        for chat_id in chat_ids:
            raw = self._raw.get(chat_id)
            if raw is None:
                raise LookupError(f"В экспорте нет чата {chat_id}")
            items = []
            for msg in raw.get("messages", []):
                if msg.get("type") != "message":
                    continue  # служебные: создание группы, закрепы и т. п.
                text = flatten_text(msg.get("text")).strip()
                if not text:
                    continue  # фото, стикеры и голосовые без подписи
                date = datetime.fromisoformat(msg["date"])
                if since and date < since:
                    continue
                items.append(
                    Message(
                        chat_id=chat_id,
                        message_id=int(msg["id"]),
                        date=date,
                        author=msg.get("from"),
                        author_id=msg.get("from_id"),
                        text=text,
                        reply_to=msg.get("reply_to_message_id"),
                        is_outgoing=self._is_outgoing(msg),
                    )
                )
            items.sort(key=lambda m: (m.date, m.message_id))
            yield from items
