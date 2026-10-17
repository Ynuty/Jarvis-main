"""Хранение секретов: сессия Telegram, api_id и api_hash.

Сессия Telegram — это полный ключ от аккаунта: кто её украдёт, сможет читать
и писать от имени пользователя, двухфакторная защита не поможет. Поэтому она
хранится не в файле проекта, а в хранилище учётных данных ОС через keyring.
На Windows это Диспетчер учётных данных (Credential Manager, защита DPAPI).
"""

from __future__ import annotations

from typing import Protocol

SERVICE = "jarvis"


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringStore:
    """Секреты в хранилище учётных данных ОС."""

    def __init__(self, service: str = SERVICE):
        try:
            import keyring  # noqa: F401
        except ImportError as e:  # pragma: no cover - зависит от окружения
            raise RuntimeError(
                "Для хранения сессии нужен пакет keyring: pip install \"jarvis[secure]\""
            ) from e
        self.service = service

    def get(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(self.service, key)

    def set(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service, key, value)

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self.service, key)
        except PasswordDeleteError:
            pass


class MemoryStore:
    """Секреты в памяти — для тестов."""

    def __init__(self, initial: dict[str, str] | None = None):
        self._data = dict(initial or {})

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
