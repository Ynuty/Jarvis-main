"""
============================================================
 База — тонкая обёртка над sqlite3. Одно соединение на процесс,
 доступ из asyncio-кода синхронный (запросы микроскопические),
 запись сериализуется блокировкой.
============================================================
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .. import config

_SCHEMA = Path(__file__).with_name("schema.sql")


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(_SCHEMA.read_text(encoding="utf-8"))

    def q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchall()

    def one(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchone()

    def run(self, sql: str, args: Iterable[Any] = ()) -> int:
        """Выполняет запись, возвращает lastrowid."""
        with self.lock:
            return self.conn.execute(sql, tuple(args)).lastrowid or 0

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def loads(s: str | None, fallback: Any = None) -> Any:
    if s is None:
        return fallback
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return fallback


_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        config.ensure_dirs()
        _db = DB(config.DB_PATH)
    return _db


def set_db(db: DB) -> None:
    """Подмена базы — для тестов и импорта профиля."""
    global _db
    _db = db
