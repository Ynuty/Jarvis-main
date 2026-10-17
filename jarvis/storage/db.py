"""Локальная база SQLite: чаты, сообщения, задачи и журнал действий.

База лежит в папке данных пользователя, а не в папке проекта:
- Windows: %LOCALAPPDATA%\\Jarvis\\jarvis.db
- другие ОС: ~/.local/share/jarvis/jarvis.db
Путь можно переопределить переменной окружения JARVIS_DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from jarvis.models import STATUS_DISMISSED, STATUS_DONE, STATUS_OPEN, Chat, Message, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id      TEXT PRIMARY KEY,
    title   TEXT NOT NULL,
    kind    TEXT NOT NULL,
    source  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    chat_id     TEXT NOT NULL,
    message_id  INTEGER NOT NULL,
    date        TEXT NOT NULL,
    author      TEXT,
    author_id   TEXT,
    text        TEXT NOT NULL,
    reply_to    INTEGER,
    is_outgoing INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT NOT NULL,
    message_id   INTEGER NOT NULL,
    title        TEXT NOT NULL,
    requested_by TEXT,
    due_at       TEXT,
    due_text     TEXT,
    assignee     TEXT NOT NULL,
    confidence   REAL NOT NULL,
    status       TEXT NOT NULL,
    source_text  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    details TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    env = os.environ.get("JARVIS_DB")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Jarvis"
    else:
        base = Path.home() / ".local" / "share" / "jarvis"
    return base / "jarvis.db"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------- чаты и сообщения ----------

    def upsert_chat(self, chat: Chat, source: str) -> None:
        self.conn.execute(
            "INSERT INTO chats(id, title, kind, source) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, kind=excluded.kind, source=excluded.source",
            (chat.id, chat.title, chat.kind, source),
        )
        self.conn.commit()

    def chat_title(self, chat_id: str) -> str:
        row = self.conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return row["title"] if row else chat_id

    def add_messages(self, messages: list[Message]) -> list[Message]:
        """Сохраняет сообщения и возвращает только новые — их и разбираем на задачи."""
        new = []
        for m in messages:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO messages(chat_id, message_id, date, author, author_id, text, reply_to, is_outgoing) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m.chat_id, m.message_id, m.date.isoformat(), m.author, m.author_id, m.text, m.reply_to, int(m.is_outgoing)),
            )
            if cur.rowcount:
                new.append(m)
        self.conn.commit()
        return new

    # ---------- задачи ----------

    def add_task(self, task: Task) -> bool:
        """Добавляет задачу. Повторная задача из того же сообщения не создаётся."""
        now = _now()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO tasks(chat_id, message_id, title, requested_by, due_at, due_text, assignee, "
            "confidence, status, source_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.chat_id, task.message_id, task.title, task.requested_by,
                task.due_at.isoformat() if task.due_at else None, task.due_text,
                task.assignee, task.confidence, task.status, task.source_text, now, now,
            ),
        )
        self.conn.commit()
        if cur.rowcount:
            task.id = cur.lastrowid
            return True
        return False

    def list_tasks(self, status: str | None = STATUS_OPEN) -> list[Task]:
        sql = "SELECT * FROM tasks"
        args: tuple = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        # Сначала с ближайшим сроком, задачи без срока — в конце
        sql += " ORDER BY due_at IS NULL, due_at, created_at"
        return [self._row_to_task(r) for r in self.conn.execute(sql, args)]

    def get_task(self, task_id: int) -> Task | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def set_status(self, task_id: int, status: str) -> bool:
        if status not in (STATUS_OPEN, STATUS_DONE, STATUS_DISMISSED):
            raise ValueError(f"Неизвестный статус: {status}")
        cur = self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), task_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row_to_task(r: sqlite3.Row) -> Task:
        return Task(
            id=r["id"],
            title=r["title"],
            chat_id=r["chat_id"],
            message_id=r["message_id"],
            source_text=r["source_text"],
            requested_by=r["requested_by"],
            due_at=_dt(r["due_at"]),
            due_text=r["due_text"],
            assignee=r["assignee"],
            confidence=r["confidence"],
            status=r["status"],
            created_at=_dt(r["created_at"]),
        )

    # ---------- журнал ----------

    def log(self, kind: str, **details) -> None:
        """Журнал действий ассистента: пользователь видит, что и когда сделано."""
        self.conn.execute(
            "INSERT INTO events(ts, kind, details) VALUES (?, ?, ?)",
            (_now(), kind, json.dumps(details, ensure_ascii=False, default=str)),
        )
        self.conn.commit()

    def list_events(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"ts": r["ts"], "kind": r["kind"], **json.loads(r["details"])} for r in rows]
