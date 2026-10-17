"""Источник: живое подключение к аккаунту Telegram — только чтение.

Работает через клиентский API Telegram (библиотека Telethon) прямо на компьютере
пользователя, с его IP. Каждый пользователь получает собственные api_id и api_hash
на https://my.telegram.org — общий ключ приложения не зашивается в программу.

Ограничения, которые соблюдаются в коде:
- клиент только читает: любой запрос на отправку, правку, удаление, реакцию,
  отметку «прочитано», смену статуса «в сети» и т. п. отклоняется до выхода в сеть
  (ReadOnlyViolation);
- запросы идут с паузами, при FloodWait клиент ждёт, а не повторяет запрос сразу;
- сессия хранится в хранилище учётных данных ОС (см. jarvis.secrets);
- данные из Telegram не используются для обучения моделей (правила Telegram API, п. 1.5).

Telethon импортируется лениво: остальной Джарвис работает и без него.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Callable, Iterable, Iterator

from jarvis.models import Chat, Message
from jarvis.secrets import SecretStore

KEY_SESSION = "telegram.session"
KEY_API_ID = "telegram.api_id"
KEY_API_HASH = "telegram.api_hash"

# Запросы Telegram API, которые что-то меняют от имени пользователя.
# Сравниваем по началу имени класса запроса (например, SendMessageRequest).
FORBIDDEN_REQUEST_PREFIXES = (
    "Send", "Edit", "Delete", "Forward", "Read", "SetTyping", "UpdateStatus",
    "UpdateProfile", "UpdateUsername", "UpdatePinned", "ToggleDialogPin",
    "MarkDialogUnread", "SaveDraft", "ClearAllDrafts", "Join", "Leave",
    "ImportChatInvite", "Block", "Unblock", "Report", "Create", "Invite",
    "AddChatUser", "DeleteChatUser", "Migrate", "Upload", "SaveFile",
    "SetBotCallbackAnswer", "Vote", "Install", "Uninstall", "Toggle",
    "UpdateNotifySettings", "ResetNotifySettings", "SetPrivacy",
    "AcceptContact", "AddContact", "ImportContacts",
)


# Исключения: запросы входа, которые формально начинаются с запретного слова.
# Ключ — (модуль TL, имя класса), чтобы не пропустить одноимённые запросы из других разделов.
ALLOWED_EXCEPTIONS = {
    ("auth", "SendCodeRequest"),   # Telegram присылает код для входа
}


class ReadOnlyViolation(RuntimeError):
    """Попытка сделать что-то кроме чтения."""


def check_read_only(request) -> None:
    """Пропускает только читающие запросы. Вложенные списки проверяет целиком."""
    if isinstance(request, (list, tuple)):
        for r in request:
            check_read_only(r)
        return
    name = type(request).__name__
    module = type(request).__module__.rsplit(".", 1)[-1]
    if (module, name) in ALLOWED_EXCEPTIONS:
        return
    if name.startswith(FORBIDDEN_REQUEST_PREFIXES):
        raise ReadOnlyViolation(f"Джарвис только читает Telegram, запрос {name} запрещён")
    inner = getattr(request, "query", None)  # обёртки вида InvokeWithLayer(query=...)
    if inner is not None and inner is not request:
        check_read_only(inner)


def _make_client_class():
    from telethon import TelegramClient

    class ReadOnlyTelegramClient(TelegramClient):
        async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
            check_read_only(request)
            return await super()._call(
                sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
            )

    return ReadOnlyTelegramClient


def _chat_kind(dialog) -> str:
    if dialog.is_user:
        return "private"
    if dialog.is_group:
        return "group"
    if dialog.is_channel:
        return "channel"
    return "unknown"


def _to_local_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


class TelegramLiveSource:
    name = "telegram_live"

    def __init__(
        self,
        store: SecretStore,
        *,
        request_delay: float = 0.7,
        max_messages_per_chat: int = 500,
        max_flood_wait: int = 120,
    ):
        self.store = store
        self.request_delay = request_delay
        self.max_messages_per_chat = max_messages_per_chat
        self.max_flood_wait = max_flood_wait
        self._loop = asyncio.new_event_loop()
        self._client = None

    # ---------- настройка и вход ----------

    def save_api_credentials(self, api_id: int, api_hash: str) -> None:
        self.store.set(KEY_API_ID, str(int(api_id)))
        self.store.set(KEY_API_HASH, api_hash.strip())

    def has_api_credentials(self) -> bool:
        return bool(self.store.get(KEY_API_ID) and self.store.get(KEY_API_HASH))

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.has_api_credentials():
            raise RuntimeError(
                "Нет api_id и api_hash. Получите их на https://my.telegram.org "
                "(раздел API development tools) и выполните: jarvis live setup"
            )
        try:
            from telethon.sessions import StringSession
        except ImportError as e:  # pragma: no cover - зависит от окружения
            raise RuntimeError(
                "Для живого подключения нужен Telethon: pip install \"jarvis[telegram]\""
            ) from e
        from jarvis import __version__

        cls = _make_client_class()
        session = StringSession(self.store.get(KEY_SESSION) or "")
        api_id = int(self.store.get(KEY_API_ID))
        api_hash = self.store.get(KEY_API_HASH)

        async def create():
            # Клиент создаётся внутри своего цикла событий
            return cls(
                session,
                api_id,
                api_hash,
                device_model="Jarvis (локальный ассистент)",
                app_version=__version__,
                receive_updates=False,   # не подписываемся на поток обновлений
            )

        self._client = self._run(create())
        return self._client

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _save_session(self) -> None:
        self.store.set(KEY_SESSION, self._client.session.save())

    def is_authorized(self) -> bool:
        client = self._get_client()

        async def check():
            await client.connect()
            return await client.is_user_authorized()

        return self._run(check())

    def login(
        self,
        phone: str,
        code_callback: Callable[[], str],
        password_callback: Callable[[], str],
    ) -> None:
        """Вход по номеру: Telegram пришлёт код в приложение, при 2FA спросим пароль."""
        from telethon.errors import SessionPasswordNeededError

        client = self._get_client()

        async def do_login():
            await client.connect()
            if await client.is_user_authorized():
                return
            await client.send_code_request(phone)
            try:
                await client.sign_in(phone=phone, code=code_callback().strip())
            except SessionPasswordNeededError:
                await client.sign_in(password=password_callback())

        self._run(do_login())
        self._save_session()

    def logout(self) -> None:
        """Завершает сессию в Telegram и удаляет её с компьютера."""
        if self.store.get(KEY_SESSION):
            client = self._get_client()

            async def do_logout():
                await client.connect()
                await client.log_out()

            try:
                self._run(do_logout())
            finally:
                self.store.delete(KEY_SESSION)
                self._client = None

    def close(self) -> None:
        if self._client is not None:
            self._run(self._client.disconnect())
        self._loop.close()

    # ---------- чтение ----------

    def _with_flood_wait(self, make_coro):
        from telethon.errors import FloodWaitError

        while True:
            try:
                return self._run(make_coro())
            except FloodWaitError as e:
                if e.seconds > self.max_flood_wait:
                    raise RuntimeError(
                        f"Telegram просит подождать {e.seconds} с. Попробуйте синхронизацию позже."
                    ) from e
                time.sleep(e.seconds + 1)

    def list_chats(self) -> list[Chat]:
        client = self._get_client()

        async def fetch():
            await client.connect()
            chats = []
            async for dialog in client.iter_dialogs():
                chats.append(Chat(id=f"tg:{dialog.id}", title=dialog.name or "Без названия", kind=_chat_kind(dialog)))
            return chats

        return self._with_flood_wait(fetch)

    def iter_messages(
        self, chat_ids: Iterable[str], since: datetime | None = None
    ) -> Iterator[Message]:
        client = self._get_client()
        limit = self.max_messages_per_chat

        for chat_id in chat_ids:
            peer = int(chat_id.removeprefix("tg:"))

            async def fetch(peer=peer, chat_id=chat_id):
                await client.connect()
                out = []
                async for msg in client.iter_messages(peer, limit=limit):
                    date = _to_local_naive(msg.date)
                    if since and date < since:
                        break  # сообщения идут от новых к старым
                    text = (msg.message or "").strip()
                    if not text:
                        continue
                    sender = msg.sender
                    author = None
                    if sender is not None:
                        author = getattr(sender, "title", None) or " ".join(
                            p for p in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if p
                        ) or None
                    out.append(
                        Message(
                            chat_id=chat_id,
                            message_id=msg.id,
                            date=date,
                            author=author,
                            author_id=f"user{msg.sender_id}" if msg.sender_id else None,
                            text=text,
                            reply_to=msg.reply_to_msg_id,
                            is_outgoing=bool(msg.out),
                        )
                    )
                return out

            messages = self._with_flood_wait(fetch)
            messages.sort(key=lambda m: (m.date, m.message_id))
            yield from messages
            time.sleep(self.request_delay)
