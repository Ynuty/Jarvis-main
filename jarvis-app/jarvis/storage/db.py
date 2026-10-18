"""SQLite-хранилище: задачи, журнал действий (events), настройки, ссылки на секреты.

Журнал events — единый источник правды: его читают безопасность (аудит),
шторка «Сделано Джарвисом», вечерний итог дня и отладка.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1 — базовая схема
    """
    CREATE TABLE tasks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        due_at      TEXT,
        duration    INTEGER,
        status      TEXT NOT NULL DEFAULT 'open',
        repeat_rule TEXT,
        created_by  TEXT NOT NULL DEFAULT 'user',
        created_at  TEXT NOT NULL,
        done_at     TEXT
    );
    CREATE TABLE events (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        skill   TEXT NOT NULL,
        tool    TEXT NOT NULL,
        args    TEXT NOT NULL DEFAULT '{}',
        risk    TEXT NOT NULL,
        status  TEXT NOT NULL,
        result  TEXT,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        source  TEXT NOT NULL DEFAULT 'user',
        undo    TEXT
    );
    CREATE INDEX events_ts ON events(ts);
    CREATE TABLE settings (
        key   TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'general',
        value TEXT NOT NULL,
        PRIMARY KEY (key, scope)
    );
    CREATE TABLE secrets (
        name    TEXT PRIMARY KEY,
        backend TEXT NOT NULL,
        ref     TEXT NOT NULL
    );
    """,
]


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class Storage:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                self._db.executescript(sql)
                self._db.execute(f"PRAGMA user_version = {i}")
            self._db.commit()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    # ---- задачи -------------------------------------------------------
    def add_task(self, title: str, due_at: datetime | None = None, duration: int | None = None,
                 created_by: str = "user", repeat_rule: str | None = None) -> int:
        cur = self._exec(
            "INSERT INTO tasks (title, due_at, duration, created_by, repeat_rule, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, due_at.isoformat() if due_at else None, duration, created_by,
             repeat_rule, now().isoformat()),
        )
        return int(cur.lastrowid)

    def get_task(self, task_id: int) -> dict | None:
        rows = self._all("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return rows[0] if rows else None

    def set_task_status(self, task_id: int, status: str) -> None:
        done_at = now().isoformat() if status == "done" else None
        self._exec("UPDATE tasks SET status = ?, done_at = ? WHERE id = ?", (status, done_at, task_id))

    def delete_task(self, task_id: int) -> None:
        self._exec("DELETE FROM tasks WHERE id = ?", (task_id,))

    def tasks_for_day(self, day: date) -> list[dict]:
        """Задачи на день: со сроком в этот день, плюс задачи без срока,
        которые ещё не сделаны или сделаны в этот день."""
        d = day.isoformat()
        return self._all(
            "SELECT * FROM tasks WHERE substr(due_at, 1, 10) = ? "
            "OR (due_at IS NULL AND (status != 'done' OR substr(done_at, 1, 10) = ?)) "
            "ORDER BY due_at IS NULL, due_at, id",
            (d, d),
        )

    def find_open_task(self, query: str, day: date) -> dict | None:
        def norm(s: str) -> str:
            return " ".join(s.lower().replace("ё", "е").split())

        q = norm(query)
        candidates = [t for t in self.tasks_for_day(day) if t["status"] != "done"]
        for t in candidates:
            if norm(t["title"]) == q:
                return t
        for t in candidates:
            if q in norm(t["title"]) or norm(t["title"]) in q:
                return t
        return None

    # ---- журнал -------------------------------------------------------
    def add_event(self, skill: str, tool: str, args: dict, risk: str, status: str,
                  result: str | None = None, task_id: int | None = None,
                  source: str = "user", undo: dict | None = None) -> int:
        cur = self._exec(
            "INSERT INTO events (ts, skill, tool, args, risk, status, result, task_id, source, undo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now().isoformat(), skill, tool, json.dumps(args, ensure_ascii=False), risk, status,
             result, task_id, source, json.dumps(undo, ensure_ascii=False) if undo else None),
        )
        return int(cur.lastrowid)

    def set_event_status(self, event_id: int, status: str) -> None:
        self._exec("UPDATE events SET status = ? WHERE id = ?", (status, event_id))

    def events_for_day(self, day: date, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events WHERE substr(ts, 1, 10) = ?"
        params: tuple = (day.isoformat(),)
        if status:
            sql += " AND status = ?"
            params += (status,)
        return self._all(sql + " ORDER BY ts DESC, id DESC", params)

    def last_undoable_event(self) -> dict | None:
        rows = self._all(
            "SELECT * FROM events WHERE status = 'done' AND undo IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
        return rows[0] if rows else None

    # ---- настройки ----------------------------------------------------
    def get_setting(self, key: str, default: Any = None, scope: str = "general") -> Any:
        rows = self._all("SELECT value FROM settings WHERE key = ? AND scope = ?", (key, scope))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: Any, scope: str = "general") -> None:
        self._exec(
            "INSERT INTO settings (key, scope, value) VALUES (?, ?, ?) "
            "ON CONFLICT(key, scope) DO UPDATE SET value = excluded.value",
            (key, scope, json.dumps(value, ensure_ascii=False)),
        )

    # ---- секреты (только ссылки) -------------------------------------
    def set_secret_ref(self, name: str, backend: str, ref: str) -> None:
        self._exec(
            "INSERT INTO secrets (name, backend, ref) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET backend = excluded.backend, ref = excluded.ref",
            (name, backend, ref),
        )

    def delete_secret_ref(self, name: str) -> None:
        self._exec("DELETE FROM secrets WHERE name = ?", (name,))

    def get_secret_ref(self, name: str) -> dict | None:
        rows = self._all("SELECT * FROM secrets WHERE name = ?", (name,))
        return rows[0] if rows else None

    # ---- «очистить данные одной кнопкой» ------------------------------
    def wipe(self) -> None:
        with self._lock:
            self._db.executescript("DELETE FROM events; DELETE FROM tasks; DELETE FROM settings;")
            self._db.commit()
