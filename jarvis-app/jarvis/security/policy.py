"""Политика безопасности: уровни риска, подтверждения, белые списки, kill-switch.

Проверяет каждое действие навыка до выполнения. Опасное действие без
подтверждения выполнить невозможно — это критерий готовности этапа 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..storage import Storage


class Risk(IntEnum):
    SAFE = 0   # только чтение: список окон, план дня
    LOW = 1    # обратимо: открыть программу, свернуть окна, добавить задачу
    HIGH = 2   # потеря данных или внешний эффект: закрыть программу, удалить, отправить

    @property
    def label(self) -> str:
        return self.name.lower()


# Источник команды. Текст из чужих сообщений — данные, а не инструкции.
TRUSTED_SOURCES = {"user", "voice", "tray"}

DEFAULT_APP_WHITELIST = [
    "telegram", "chrome", "browser", "notepad", "calculator", "explorer",
    "vscode", "spotify", "word", "excel", "safari", "finder", "steam",
]


@dataclass
class Decision:
    verdict: str          # allow | confirm | deny
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


class Policy:
    def __init__(self, storage: Storage):
        self.storage = storage

    # --- kill-switch ---------------------------------------------------
    @property
    def stopped(self) -> bool:
        return bool(self.storage.get_setting("killswitch", False))

    def stop(self) -> None:
        self.storage.set_setting("killswitch", True)

    def resume(self) -> None:
        self.storage.set_setting("killswitch", False)

    # --- белый список программ ----------------------------------------
    @property
    def app_whitelist(self) -> list[str]:
        return self.storage.get_setting("app_whitelist", DEFAULT_APP_WHITELIST)

    # --- главная проверка ---------------------------------------------
    def check(self, skill: str, tool: str, risk: Risk, args: dict, source: str) -> Decision:
        if skill == "system":
            return Decision("allow")
        if self.stopped:
            return Decision("deny", "Аварийная остановка включена. Скажите «продолжай», чтобы снять.")
        if source not in TRUSTED_SOURCES and risk > Risk.SAFE:
            return Decision("confirm", "Команда пришла из текста сообщения, а не от вас.")
        if risk >= Risk.HIGH:
            return Decision("confirm", "Действие может привести к потере данных.")
        if tool == "open_app" and args.get("app", "").lower() not in self.app_whitelist:
            return Decision("confirm", f"Программы «{args.get('app')}» нет в белом списке.")
        return Decision("allow")
