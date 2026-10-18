"""Клиент локальной LLM (Ollama на localhost; llama.cpp-сервер — через тот же
OpenAI-совместимый путь можно добавить позже).

Небольшие модели путают формат, поэтому: структурированный вывод по
JSON-схеме → валидация → один повтор с текстом ошибки → честное «не понял».
"""
from __future__ import annotations

import json
import time
import urllib.request

from ..core.router import Action
from ..skills.base import validate
from . import prompts


class LLMClient:
    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen2.5:7b-instruct",
                 timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available: bool | None = None
        self._checked_at = 0.0

    # ---- доступность --------------------------------------------------
    def enabled(self) -> bool:
        # Модель могли запустить или остановить — перепроверяем раз в 30 секунд.
        if self._available is None or time.time() - self._checked_at > 30:
            self._checked_at = time.time()
            try:
                with urllib.request.urlopen(self.url + "/api/tags", timeout=0.5) as r:
                    names = [m["name"] for m in json.load(r).get("models", [])]
                self._available = any(n.split(":")[0] == self.model.split(":")[0] for n in names)
            except (OSError, ValueError):
                self._available = False
        return self._available

    def status(self) -> dict:
        return {"enabled": self.enabled(), "model": self.model, "url": self.url}

    def _chat(self, messages: list[dict], fmt: dict | None = None) -> str:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0}, "keep_alive": "30m"}
        if fmt:
            body["format"] = fmt
        req = urllib.request.Request(self.url + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)["message"]["content"]

    # ---- план действий ------------------------------------------------
    def plan(self, text: str, tools: list[dict]) -> list[Action] | None:
        by_name = {t["name"]: t for t in tools}
        fmt = {
            "type": "object",
            "properties": {"steps": {"type": "array", "items": {
                "type": "object",
                "properties": {"tool": {"type": "string", "enum": list(by_name)},
                               "args": {"type": "object"}},
                "required": ["tool", "args"]}}},
            "required": ["steps"],
        }
        messages = [{"role": "system", "content": prompts.planner(tools)},
                    {"role": "user", "content": text}]
        for _ in range(2):  # попытка + один повтор
            try:
                raw = self._chat(messages, fmt)
            except (OSError, ValueError, KeyError):
                self._available = None
                return None
            error, plan = self._parse(raw, by_name)
            if not error:
                return plan or None
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Ошибка: {error}. Исправь и верни только JSON."}]
        return None

    @staticmethod
    def _parse(raw: str, by_name: dict) -> tuple[str | None, list[Action]]:
        try:
            data = json.loads(raw)
        except ValueError:
            return "ответ не JSON", []
        plan = []
        for step in data.get("steps", []):
            tool = by_name.get(step.get("tool"))
            if not tool:
                return f"нет инструмента {step.get('tool')}", []
            args = {k: v for k, v in (step.get("args") or {}).items() if v not in (None, "")}
            err = validate(args, tool["parameters"])
            if err:
                return f"{tool['name']}: {err}", []
            skill, _, name = tool["name"].partition(".")
            plan.append(Action(skill, name, args))
        return None, plan

    # ---- сводка чужого текста (без инструментов) ----------------------
    def summarize_untrusted(self, items: list[dict]) -> str | None:
        if not self.enabled():
            return None
        payload = json.dumps(items[:50], ensure_ascii=False)
        try:
            return self._chat([{"role": "system", "content": prompts.DIGEST},
                               {"role": "user", "content": payload}]).strip()
        except (OSError, ValueError, KeyError):
            return None
