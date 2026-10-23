"""
============================================================
 Профили и вход. Пароль или PIN → argon2id. Токен сессии живёт
 только в памяти ядра и в памяти окна. Пять неверных попыток —
 пауза 30 секунд. Экспорт профиля — зашифрованный архив
 (scrypt + AES-GCM), импорт — обратно; «удалить все мои данные» —
 профиль, его записи и секреты в хранилище ОС.
============================================================
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
import zlib
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .db import DB

ph = PasswordHasher()  # argon2id по умолчанию

PROFILE_TABLES = ["settings", "events", "messages", "summaries", "memory", "notes", "tasks", "carts", "orders",
                  "mail_accounts", "mail_moves", "rag_docs", "dataset"]


class AuthError(Exception):
    pass


@dataclass
class Token:
    profile_id: int
    name: str
    issued: float


_tokens: dict[str, Token] = {}
_fails: dict[int, list[float]] = {}


def validate_secret(kind: str, secret: str) -> None:
    if kind == "pin":
        if not re.fullmatch(r"\d{4,8}", secret):
            raise AuthError("PIN — от 4 до 8 цифр")
    elif len(secret) < 6:
        raise AuthError("Пароль — не короче 6 символов")


def list_profiles(db: DB) -> list[dict]:
    return [dict(r) for r in db.q("SELECT id, name, avatar, pw_kind, created_at FROM profiles ORDER BY id")]


def create_profile(db: DB, name: str, secret: str, kind: str = "pin", avatar: str = "") -> int:
    name = name.strip()
    if not name or len(name) > 40:
        raise AuthError("Имя — от 1 до 40 символов")
    validate_secret(kind, secret)
    if db.one("SELECT 1 FROM profiles WHERE name=?", (name,)):
        raise AuthError("Такой профиль уже есть")
    return db.run("INSERT INTO profiles(name, avatar, pw_hash, pw_kind, created_at) VALUES (?,?,?,?,?)",
                  (name, avatar, ph.hash(secret), kind, time.time()))


def verify(db: DB, profile_id: int, secret: str) -> bool:
    r = db.one("SELECT pw_hash FROM profiles WHERE id=?", (profile_id,))
    if not r:
        return False
    try:
        ok = ph.verify(r["pw_hash"], secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    if ok and ph.check_needs_rehash(r["pw_hash"]):
        db.run("UPDATE profiles SET pw_hash=? WHERE id=?", (ph.hash(secret), profile_id))
    return ok


def login(db: DB, profile_id: int, secret: str) -> str:
    now = time.time()
    fails = [t for t in _fails.get(profile_id, []) if now - t < 30]
    if len(fails) >= 5:
        raise AuthError("Слишком много попыток. Подождите 30 секунд.")
    if not verify(db, profile_id, secret):
        fails.append(now)
        _fails[profile_id] = fails
        raise AuthError("Неверный PIN или пароль")
    _fails.pop(profile_id, None)
    name = db.one("SELECT name FROM profiles WHERE id=?", (profile_id,))["name"]
    tok = secrets.token_urlsafe(32)
    _tokens[tok] = Token(profile_id, name, now)
    return tok


def check(token: str | None) -> Token:
    t = _tokens.get(token or "")
    if not t:
        raise AuthError("Нужен вход")
    return t


def logout(token: str) -> None:
    _tokens.pop(token, None)


def change_secret(db: DB, profile_id: int, old: str, new: str, kind: str) -> None:
    if not verify(db, profile_id, old):
        raise AuthError("Неверный текущий PIN или пароль")
    validate_secret(kind, new)
    db.run("UPDATE profiles SET pw_hash=?, pw_kind=? WHERE id=?", (ph.hash(new), kind, profile_id))


def set_voice_phrase(db: DB, profile_id: int, phrase: str | None) -> None:
    """Вход по голосовой фразе: храним только хеш нормализованной фразы."""
    from .text.ru import norm
    db.run("UPDATE profiles SET voice_phrase_hash=? WHERE id=?",
           (ph.hash(norm(phrase)) if phrase else None, profile_id))


def login_by_phrase(db: DB, profile_id: int, heard: str) -> str:
    from .text.ru import norm
    r = db.one("SELECT voice_phrase_hash, name FROM profiles WHERE id=?", (profile_id,))
    if not r or not r["voice_phrase_hash"]:
        raise AuthError("Голосовой вход не настроен")
    try:
        ph.verify(r["voice_phrase_hash"], norm(heard))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise AuthError("Фраза не совпала") from None
    tok = secrets.token_urlsafe(32)
    _tokens[tok] = Token(profile_id, r["name"], time.time())
    return tok


# ---------- удаление, экспорт, импорт ----------

def wipe_profile(db: DB, profile_id: int) -> None:
    from .skills import mail_conn
    for r in db.q("SELECT secret_ref FROM mail_accounts WHERE profile_id=?", (profile_id,)):
        mail_conn.drop_secret(r["secret_ref"])
    db.run("DELETE FROM profiles WHERE id=?", (profile_id,))   # каскад удалит остальное
    for tok, t in list(_tokens.items()):
        if t.profile_id == profile_id:
            _tokens.pop(tok, None)


def _kdf(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def export_profile(db: DB, profile_id: int, password: str) -> bytes:
    """JSON всех таблиц профиля → zlib → AES-GCM. Пароли почты не экспортируются."""
    if len(password) < 6:
        raise AuthError("Пароль архива — не короче 6 символов")
    data: dict = {"version": 1, "profile": dict(db.one("SELECT * FROM profiles WHERE id=?", (profile_id,)))}
    for t in PROFILE_TABLES:
        rows = db.q(f"SELECT * FROM {t} WHERE profile_id=?", (profile_id,))  # noqa: S608 — имя таблицы из белого списка
        data[t] = [{k: (v.hex() if isinstance(v, bytes) else v) for k, v in dict(r).items()} for r in rows]
    doc_ids = [d["id"] for d in data["rag_docs"]]
    data["rag_chunks"] = [{k: (v.hex() if isinstance(v, bytes) else v) for k, v in dict(r).items()}
                          for i in doc_ids for r in db.q("SELECT * FROM rag_chunks WHERE doc_id=?", (i,))]
    for acc in data["mail_accounts"]:
        acc["secret_ref"] = ""
    raw = zlib.compress(json.dumps(data, ensure_ascii=False).encode())
    salt, nonce = os.urandom(16), os.urandom(12)
    return b"JRVS1" + salt + nonce + AESGCM(_kdf(password, salt)).encrypt(nonce, raw, b"jarvis-profile")


def import_profile(db: DB, blob: bytes, password: str, new_name: str | None = None) -> int:
    if not blob.startswith(b"JRVS1"):
        raise AuthError("Это не архив профиля Джарвиса")
    salt, nonce, ct = blob[5:21], blob[21:33], blob[33:]
    try:
        raw = AESGCM(_kdf(password, salt)).decrypt(nonce, ct, b"jarvis-profile")
    except Exception:  # noqa: BLE001 — InvalidTag: неверный пароль или повреждён файл
        raise AuthError("Неверный пароль архива или файл повреждён") from None
    data = json.loads(zlib.decompress(raw))
    p = data["profile"]
    name = new_name or p["name"]
    while db.one("SELECT 1 FROM profiles WHERE name=?", (name,)):
        name += " (импорт)"
    pid = db.run("INSERT INTO profiles(name, avatar, pw_hash, pw_kind, voice_phrase_hash, created_at) VALUES (?,?,?,?,?,?)",
                 (name, p.get("avatar", ""), p["pw_hash"], p["pw_kind"], p.get("voice_phrase_hash"), p["created_at"]))
    doc_map: dict[int, int] = {}
    for t in PROFILE_TABLES:
        for row in data.get(t, []):
            row = dict(row)
            old_id = row.pop("id", None)
            row["profile_id"] = pid
            if t == "summaries":
                row.pop("id", None)
            cols = ",".join(row)
            new_id = db.run(f"INSERT INTO {t}({cols}) VALUES ({','.join('?' * len(row))})",  # noqa: S608
                            list(row.values()))
            if t == "rag_docs" and old_id is not None:
                doc_map[old_id] = new_id
    for ch in data.get("rag_chunks", []):
        if ch["doc_id"] in doc_map:
            db.run("INSERT INTO rag_chunks(doc_id, idx, text, emb) VALUES (?,?,?,?)",
                   (doc_map[ch["doc_id"]], ch["idx"], ch["text"], bytes.fromhex(ch["emb"]) if ch.get("emb") else None))
    return pid
