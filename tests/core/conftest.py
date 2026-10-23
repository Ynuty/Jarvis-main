"""Общие фикстуры: временная база, сессия с перехватом событий, поддельная LLM."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("JARVIS_HOME", tempfile.mkdtemp(prefix="jarvis-test-"))

from jarvis import auth, db as dbmod  # noqa: E402
from jarvis.engines import engines  # noqa: E402
from jarvis.session import Session  # noqa: E402


class FakeOllama:
    """Отдаёт заранее заданные ответы, запоминает запросы."""

    def __init__(self):
        self.replies: list[str] = []
        self.calls: list[dict] = []

    def queue(self, *objs):
        for o in objs:
            self.replies.append(o if isinstance(o, str) else json.dumps(o, ensure_ascii=False))

    async def alive(self):
        return True

    async def has_model(self, name):
        return True

    async def models(self):
        return ["qwen2.5:7b"]

    async def warm(self, model):
        return None

    async def chat_stream(self, messages, model, schema=None, **kw):
        self.calls.append({"messages": messages, "schema": schema})
        text = self.replies.pop(0) if self.replies else json.dumps({"say": "Хорошо, сэр.", "action": ""})
        for i in range(0, len(text), 7):
            yield text[i:i + 7]
            await asyncio.sleep(0)

    async def chat(self, messages, model, **kw):
        return "".join([p async for p in self.chat_stream(messages, model, **kw)])

    async def embed(self, texts, model):
        import hashlib
        out = []
        for t in texts:
            h = hashlib.sha256(t.lower().encode()).digest()
            out.append([b / 255 for b in h] * 4)
        return out


@pytest.fixture
def db(tmp_path: Path):
    d = dbmod.DB(tmp_path / "t.db")
    dbmod.set_db(d)
    yield d
    d.close()


@pytest.fixture
def llm(monkeypatch):
    f = FakeOllama()
    monkeypatch.setattr(engines, "ollama", f)
    monkeypatch.setattr(engines, "llm_ok", True)
    return f


class Capture:
    def __init__(self):
        self.events: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, m):
        self.events.append(m)

    async def send_bytes(self, b):
        self.audio.append(b)

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]

    def said(self):
        return " ".join(e["text"] for e in self.events if e.get("type") in ("say", "audio"))


@pytest.fixture
async def session(db, llm):
    pid = auth.create_profile(db, "Тони", "1234")
    s = Session(db, pid, "Тони")
    cap = Capture()
    s.attach(cap.send_json, cap.send_bytes)
    s.cap = cap
    yield s
    s.clear_timers()
    if s.speaker:
        s.speaker.cancel()


async def say(s: Session, text: str):
    """Реплика текстом + дождаться завершения хода."""
    await s.handle_utterance(text, source="text")
    if s.turn:
        try:
            await asyncio.wait_for(asyncio.shield(s.turn), 5)
        except asyncio.TimeoutError:
            pass
    await asyncio.sleep(0.05)


async def wait_confirm(s: Session, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if s.pending:
            return s.pending
        await asyncio.sleep(0.02)
    raise AssertionError("не дождался карточки подтверждения")
