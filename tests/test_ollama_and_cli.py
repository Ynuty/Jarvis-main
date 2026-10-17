import io
import json

import pytest

from jarvis import cli
from jarvis.llm import ollama
from jarvis.llm.base import LLMError


def test_ollama_refuses_remote_host():
    with pytest.raises(ValueError, match="localhost"):
        ollama.OllamaClient(url="https://api.example.com")


def test_ollama_parses_structured_answer(monkeypatch):
    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["body"] = json.loads(req.data)
        return Resp(json.dumps({"message": {"content": '{"is_task": true}'}}).encode())

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)
    client = ollama.OllamaClient(model="m")
    assert client.complete_json("sys", "user", {"type": "object"}) == {"is_task": True}
    assert sent["url"] == "http://127.0.0.1:11434/api/chat"
    assert sent["body"]["format"] == {"type": "object"}
    assert sent["body"]["options"]["temperature"] == 0


def test_ollama_unavailable_is_llm_error(monkeypatch):
    def boom(req, timeout):
        raise ollama.urllib.error.URLError("connection refused")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match="ollama pull"):
        ollama.OllamaClient().complete_json("s", "u", {})


def test_cli_import_tasks_done(tmp_path, single_export, capsys):
    db = str(tmp_path / "j.db")
    assert cli.main(["--db", db, "import", str(single_export), "--chat", "Курсовой проект", "--me", "Саша"]) == 0
    out = capsys.readouterr().out
    assert "Подготовь слайды по рынку" in out
    assert "от: Анна" in out

    assert cli.main(["--db", db, "done", "1"]) == 0
    assert cli.main(["--db", db, "tasks"]) == 0
    out = capsys.readouterr().out
    assert "[1]" not in out.split("Сделано:")[-1]

    assert cli.main(["--db", db, "import", str(single_export), "--chat", "Нет такого"]) == 1
    assert "Чат не найден" in capsys.readouterr().err
