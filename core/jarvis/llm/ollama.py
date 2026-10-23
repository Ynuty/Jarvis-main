"""
============================================================
 Клиент Ollama (localhost:11434): чат с потоком, структурированный
 вывод по JSON-схеме, эмбеддинги, скачивание моделей с прогрессом.
 Никаких запросов наружу: Ollama — локальный сервер.
============================================================
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .. import config


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, url: str | None = None, timeout: float = 120.0) -> None:
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        # trust_env=False: системный прокси не должен перехватывать localhost
        return httpx.AsyncClient(base_url=self.url, timeout=timeout or self.timeout, trust_env=False)

    async def alive(self) -> bool:
        try:
            async with self._client(3) as c:
                r = await c.get("/api/version")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def models(self) -> list[str]:
        async with self._client(5) as c:
            r = await c.get("/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]

    async def has_model(self, name: str) -> bool:
        try:
            names = await self.models()
        except httpx.HTTPError:
            return False
        base = name if ":" in name else name + ":latest"
        return name in names or base in names

    async def chat_stream(self, messages: list[dict], model: str, *, schema: dict | None = None,
                          temperature: float = 0.6, num_ctx: int = 4096,
                          keep_alive: str = "30m") -> AsyncIterator[str]:
        body = {
            "model": model, "messages": messages, "stream": True, "keep_alive": keep_alive,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if schema is not None:
            body["format"] = schema
        async with self._client() as c:
            async with c.stream("POST", "/api/chat", json=body) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "replace")
                    raise OllamaError(f"ollama {r.status_code}: {text[:200]}")
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise OllamaError(msg["error"])
                    piece = msg.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if msg.get("done"):
                        break

    async def chat(self, messages: list[dict], model: str, **kw) -> str:
        return "".join([p async for p in self.chat_stream(messages, model, **kw)])

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        async with self._client(60) as c:
            r = await c.post("/api/embed", json={"model": model, "input": texts})
            if r.status_code != 200:
                raise OllamaError(f"embed {r.status_code}: {r.text[:200]}")
            return r.json()["embeddings"]

    async def pull(self, name: str) -> AsyncIterator[dict]:
        """Поток прогресса скачивания: {status, completed, total}."""
        async with self._client(None) as c:
            c.timeout = httpx.Timeout(None)
            async with c.stream("POST", "/api/pull", json={"model": name, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if line:
                        yield json.loads(line)

    async def warm(self, model: str) -> None:
        """Пустой запрос — модель загружается в видеопамять заранее."""
        async with self._client(120) as c:
            await c.post("/api/generate", json={"model": model, "prompt": "", "keep_alive": "30m"})
