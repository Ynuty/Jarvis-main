"""
============================================================
 Журнал действий (таблица events). Его читают: экран «Журнал»,
 шторка «День» («Сделано Джарвисом»), вечерний итог и отладка.
 Пароли и токены сюда не попадают: аргументы фильтруются.
============================================================
"""
from __future__ import annotations

import time
from typing import Any

from .db import DB, dumps, loads

_SECRET_KEYS = ("password", "pass", "token", "secret", "pin", "card", "cvc", "пароль")


def _scrub(args: dict | None) -> dict:
    out = {}
    for k, v in (args or {}).items():
        out[k] = "•••" if any(s in k.lower() for s in _SECRET_KEYS) else v
    return out


def log(db: DB, profile_id: int | None, *, skill: str, tool: str, args: dict | None = None,
        risk: str = "read", status: str, result: str = "", summary: str = "", source: str = "user",
        task_id: int | None = None) -> int:
    return db.run(
        "INSERT INTO events(ts, profile_id, skill, tool, args, risk, status, result, summary, source, task_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), profile_id, skill, tool, dumps(_scrub(args)), risk, status, result[:2000], summary[:300],
         source, task_id))


def update(db: DB, event_id: int, status: str, result: str = "") -> None:
    db.run("UPDATE events SET status=?, result=? WHERE id=?", (status, result[:2000], event_id))


def row(db: DB, event_id: int) -> dict[str, Any] | None:
    r = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    return as_dict(r) if r else None


def as_dict(r) -> dict[str, Any]:
    d = dict(r)
    d["args"] = loads(d.get("args"), {})
    return d


def recent(db: DB, profile_id: int, limit: int = 100, since: float | None = None,
           skill: str | None = None) -> list[dict]:
    sql = "SELECT * FROM events WHERE profile_id=?"
    args: list[Any] = [profile_id]
    if since is not None:
        sql += " AND ts>=?"
        args.append(since)
    if skill:
        sql += " AND skill=?"
        args.append(skill)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [as_dict(r) for r in db.q(sql, args)]
