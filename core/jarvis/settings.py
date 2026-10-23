"""Настройки профиля: JSON-значения в таблице settings поверх значений по умолчанию."""
from __future__ import annotations

import copy
from typing import Any

from . import config
from .db import DB, dumps, loads


class Settings:
    def __init__(self, db: DB, profile_id: int) -> None:
        self.db = db
        self.profile_id = profile_id
        self._cache: dict[str, Any] | None = None

    def all(self) -> dict[str, Any]:
        if self._cache is None:
            data = copy.deepcopy(config.DEFAULT_SETTINGS)
            for r in self.db.q("SELECT key, value FROM settings WHERE profile_id=?", (self.profile_id,)):
                data[r["key"]] = loads(r["value"])
            self._cache = data
        return self._cache

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.all().get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        self.db.run("INSERT INTO settings(profile_id, key, value) VALUES (?,?,?) "
                    "ON CONFLICT(profile_id, key) DO UPDATE SET value=excluded.value",
                    (self.profile_id, key, dumps(value)))
        self.all()[key] = value

    def update(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            self.set(k, v)
