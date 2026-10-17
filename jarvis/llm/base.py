from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    """Модель недоступна или ответила не по схеме."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """Возвращает ответ модели, разобранный из JSON по заданной схеме."""
        ...
