"""Локальный сервер ядра: отдаёт интерфейс и JSON-API на 127.0.0.1.

Защита: слушаем только localhost, проверяем Host (против DNS rebinding) и
требуем токен сессии в заголовке X-Jarvis-Token — чужая веб-страница не
сможет отправить команду ядру (кастомный заголовок требует CORS, а мы его
не разрешаем).
"""
from __future__ import annotations

import json
import mimetypes
import secrets
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import Orchestrator
from .llm import LLMClient
from .resources import PROFILES, ModelManager
from .storage.secrets import Secrets
from .voice import stt, stt_api
from .voice.echo_guard import EchoGuard
from .voice.tts import TTS

WEB = Path(__file__).parent / "ui" / "web"
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
MAX_BODY = 16 * 1024 * 1024


class App:
    def __init__(self, orchestrator: Orchestrator, llm: LLMClient | None, models: ModelManager,
                 data_dir: Path):
        self.o = orchestrator
        self.llm = llm
        self.models = models
        self.secrets = Secrets(orchestrator.storage, data_dir)
        self.guard = EchoGuard()
        self.tts = TTS(self.guard)
        self.token = secrets.token_urlsafe(24)

    @property
    def storage(self):
        return self.o.storage

    def day(self) -> dict:
        today = date.today()
        tasks = self.storage.tasks_for_day(today)
        events = [e for e in self.storage.events_for_day(today) if e["status"] in ("done", "undone")]
        now = datetime.now()
        return {
            "date_label": f"{WEEKDAYS[today.weekday()]}, {today.day} {MONTHS[today.month - 1]}",
            "now_minutes": now.hour * 60 + now.minute,
            "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"],
                       "time": t["due_at"][11:16] if t["due_at"] and t["due_at"][:10] == today.isoformat() else None,
                       "created_by": t["created_by"]} for t in tasks],
            "done": [{"id": e["id"], "time": e["ts"][11:16], "text": e["result"], "status": e["status"],
                      "skill": e["skill"]} for e in events[:30]],
            "counts": {"done": sum(t["status"] == "done" for t in tasks), "total": len(tasks)},
        }

    # ---- распознавание речи: локально или через API ---------------------
    def stt_api_key(self) -> str | None:
        try:
            return self.secrets.get(stt_api.SECRET_NAME)
        except (OSError, RuntimeError):
            return None

    def stt_backend(self) -> str | None:
        """auto: API, если задан ключ; иначе локальный Whisper, если установлен."""
        mode = self.storage.get_setting("stt_backend", "auto")
        has_key = self.storage.get_secret_ref(stt_api.SECRET_NAME) is not None
        if mode == "api" or (mode == "auto" and has_key):
            return "api"
        if stt.available():
            return "local"
        return None

    def transcribe(self, audio: bytes, suffix: str) -> str:
        if self.stt_backend() == "api":
            provider = self.storage.get_setting("stt_provider", "groq")
            return stt_api.transcribe(audio, suffix, self.stt_api_key() or "", provider)
        return stt.transcribe(self.models, audio, suffix)

    def state(self) -> dict:
        return {
            "day": self.day(),
            "stopped": self.o.policy.stopped,
            "llm": self.llm.status() if self.llm else {"enabled": False},
            "voice": {"stt": self.stt_backend() is not None, "backend": self.stt_backend(),
                      "mode": self.storage.get_setting("stt_backend", "auto"),
                      "local_available": stt.available(),
                      "api_key_set": self.storage.get_secret_ref(stt_api.SECRET_NAME) is not None,
                      "provider": self.storage.get_setting("stt_provider", "groq"),
                      "providers": {k: v["title"] for k, v in stt_api.PROVIDERS.items()},
                      "tts": self.tts.available,
                      "tts_on": bool(self.storage.get_setting("tts_on", False))},
            "accent": self.storage.get_setting("accent", "#5EEAD4"),
            "profile": self.models.profile,
            "profiles": {k: v["title"] for k, v in PROFILES.items()},
            "dry_run": self.o.dry_run,
        }

    def respond(self, result: dict) -> dict:
        if result.get("status") in ("done", "error", "unknown", "stopped") and \
                self.storage.get_setting("tts_on", False):
            self.tts.speak(result.get("say", ""))
        result["day"] = self.day()
        result["stopped"] = self.o.policy.stopped
        return result


def make_handler(app: App, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis"

        def log_message(self, fmt, *args):  # тише в консоли
            pass

        # ---- утилиты ---------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: dict, code: int = 200) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def _authed(self) -> bool:
            return self._host_ok() and secrets.compare_digest(self.headers.get("X-Jarvis-Token", ""), app.token)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("слишком большой запрос")
            return self.rfile.read(n) if n else b""

        # ---- GET -------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            path = self.path.split("?", 1)[0]
            if path == "/":
                html = (WEB / "index.html").read_text("utf-8").replace("{{TOKEN}}", app.token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if path.startswith("/api/"):
                if not self._authed():
                    return self._json({"error": "unauthorized"}, 401)
                if path == "/api/state":
                    return self._json(app.state())
                if path == "/api/day":
                    return self._json(app.day())
                return self._json({"error": "not found"}, 404)
            file = (WEB / path.lstrip("/")).resolve()
            if WEB.resolve() in file.parents and file.is_file():
                ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, file.read_bytes(), ctype)
            return self._send(404, b"not found", "text/plain")

        # ---- POST ------------------------------------------------------
        def do_POST(self):
            if not self._authed():
                return self._json({"error": "unauthorized"}, 401)
            try:
                raw = self._body()
                path = self.path.split("?", 1)[0]
                if path == "/api/voice":
                    return self._voice(raw)
                data = json.loads(raw or b"{}")
                o = app.o
                if path == "/api/command":
                    text = str(data.get("text", ""))[:500]
                    return self._json(app.respond(o.handle(text, source="user")))
                if path == "/api/confirm":
                    return self._json(app.respond(o.confirm(str(data.get("id")), bool(data.get("accept")))))
                if path == "/api/undo":
                    return self._json(app.respond(o.run_action("system", "undo")))
                if path == "/api/stop":
                    return self._json(app.respond(o.run_action("system", "stop")))
                if path == "/api/resume":
                    return self._json(app.respond(o.run_action("system", "resume")))
                if path == "/api/task/toggle":
                    task = app.storage.get_task(int(data.get("id", 0)))
                    if not task:
                        return self._json({"error": "нет задачи"}, 404)
                    tool = "reopen_task" if task["status"] == "done" else "complete_task"
                    return self._json(app.respond(o.run_action("day", tool, {"task_id": task["id"]})))
                if path == "/api/settings":
                    return self._settings(data)
                if path == "/api/wipe":
                    app.storage.wipe()
                    app.secrets.delete(stt_api.SECRET_NAME)
                    return self._json(app.state())
                return self._json({"error": "not found"}, 404)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)

        def _voice(self, raw: bytes):
            if app.guard.muted:
                return self._json({"status": "error", "say": "Я ещё говорю — повторите через секунду"}, 409)
            ctype = self.headers.get("Content-Type", "audio/webm")
            suffix = ".ogg" if "ogg" in ctype else ".wav" if "wav" in ctype else ".webm"
            try:
                text = app.transcribe(raw, suffix)
            except (stt.STTUnavailable, stt_api.STTApiError) as exc:
                return self._json({"status": "error", "say": str(exc)}, 502)
            if not text:
                return self._json(app.respond({"status": "unknown", "say": "Не расслышал. Попробуйте ещё раз",
                                               "steps": [], "ui": {}, "heard": ""}))
            return self._json(app.respond(app.o.handle(text, source="voice")))

        def _settings(self, data: dict):
            s = app.storage
            accent = data.get("accent")
            if isinstance(accent, str) and len(accent) == 7 and accent.startswith("#"):
                int(accent[1:], 16)
                s.set_setting("accent", accent)
            if "tts_on" in data:
                s.set_setting("tts_on", bool(data["tts_on"]))
            if data.get("stt_backend") in ("auto", "local", "api"):
                s.set_setting("stt_backend", data["stt_backend"])
            if data.get("stt_provider") in stt_api.PROVIDERS:
                s.set_setting("stt_provider", data["stt_provider"])
            if "stt_api_key" in data:  # ключ только записывается, наружу не отдаётся
                key = str(data["stt_api_key"]).strip()
                try:
                    if key:
                        app.secrets.put(stt_api.SECRET_NAME, key)
                    else:
                        app.secrets.delete(stt_api.SECRET_NAME)
                except RuntimeError as exc:
                    return self._json({"error": str(exc)}, 400)
            if data.get("profile") in PROFILES:
                s.set_setting("profile", data["profile"], scope="device")
                app.models.set_profile(data["profile"])
                if app.llm:
                    app.llm.model = PROFILES[data["profile"]]["llm"]
                    app.llm._available = None
            return self._json(app.state())

    return Handler


def serve(app: App, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    httpd.daemon_threads = True
    return httpd
