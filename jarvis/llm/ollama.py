"""Клиент Ollama, запущенной на этом же компьютере.

По правилам проекта модель доступна только на localhost: адрес вне компьютера
пользователя клиент отказывается использовать, чтобы переписка никуда не ушла.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from jarvis.llm.base import LLMError

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, url: str = DEFAULT_URL, timeout: float = 120.0):
        host = urlparse(url).hostname
        if host not in _LOCAL_HOSTS:
            raise ValueError(
                f"Модель должна работать на этом компьютере (localhost), а не на {host!r}: "
                "переписка не должна покидать компьютер."
            )
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,           # структурированный ответ по JSON-схеме
            "stream": False,
            "options": {"temperature": 0},
        }
        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise LLMError(
                f"Локальная модель недоступна ({self.url}). Запустите Ollama и скачайте модель: "
                f"ollama pull {self.model}"
            ) from e
        content = (body.get("message") or {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Модель ответила не в формате JSON: {content[:200]!r}") from e
