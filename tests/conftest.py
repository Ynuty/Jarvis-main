from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def single_export() -> Path:
    return DATA / "export_single_chat.json"


@pytest.fixture
def full_export() -> Path:
    return DATA / "export_full_account.json"


class FakeLLM:
    """Подставная модель: возвращает заранее заданные ответы по очереди."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        item = self.responses.pop(0) if self.responses else {"is_task": False, "title": "", "assignee": "other",
                                                               "requested_by": None, "due_text": None, "confidence": 0}
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_llm_cls():
    return FakeLLM
