"""Тесты ядра: роутер, политика, журнал, откат. Запуск: python -m unittest -v"""
import json
import unittest
from datetime import date

from jarvis.core import Orchestrator
from jarvis.core.normalize import normalize
from jarvis.core.router import parse_task, route, split_steps
from jarvis.llm.client import LLMClient
from jarvis.storage import Storage


def make():
    return Orchestrator(Storage(), dry_run=True)


class RouterTest(unittest.TestCase):
    def plan(self, text):
        p = route(normalize(text))
        return [(a.name, a.args) for a in p] if p else None

    def test_compound_command_keeps_context(self):
        self.assertEqual(self.plan("Джарвис, открой Телеграм и сверни остальные окна"), [
            ("desktop.open_app", {"app": "telegram"}),
            ("desktop.minimize_all", {"except_app": "telegram"}),
        ])

    def test_and_inside_task_is_not_split(self):
        self.assertEqual(split_steps("добавь задачу купить хлеб и молоко"), ["добавь задачу купить хлеб и молоко"])

    def test_task_time_and_tomorrow(self):
        self.assertEqual(parse_task("завтра в 9 утра позвонить маме"),
                         {"day_offset": 1, "time": "09:00", "title": "позвонить маме"})
        self.assertEqual(parse_task("созвон в 5 вечера")["time"], "17:00")

    def test_site_synonym_goes_to_url(self):
        self.assertEqual(self.plan("открой ютуб"), [("desktop.open_url", {"url": "youtube.com"})])

    def test_genitive_app_name(self):
        self.assertEqual(self.plan("сверни все окна кроме хрома"),
                         [("desktop.minimize_all", {"except_app": "chrome"})])

    def test_whisper_repeat_is_one_command(self):
        self.assertEqual(self.plan("Открой стим. Открой стим."), [("desktop.open_app", {"app": "steam"})])

    def test_fuzzy_app_name(self):
        self.assertEqual(self.plan("Открой сафар."), [("desktop.open_app", {"app": "safari"})])

    def test_unknown_goes_to_llm(self):
        self.assertIsNone(self.plan("сделай мне кофе"))


class PipelineTest(unittest.TestCase):
    def test_typical_command_runs_and_is_journaled(self):
        o = make()
        r = o.handle("открой калькулятор")
        self.assertEqual(r["status"], "done")
        ev = o.storage.events_for_day(date.today(), "done")
        self.assertEqual(ev[0]["tool"], "open_app")

    def test_dangerous_action_requires_confirmation(self):
        o = make()
        r = o.handle("закрой хром")
        self.assertEqual(r["status"], "confirm")
        self.assertEqual(o.storage.events_for_day(date.today(), "done"), [])
        r = o.confirm(r["confirm"]["id"], accept=True)
        self.assertEqual(r["status"], "done")

    def test_cancelled_confirmation_does_nothing(self):
        o = make()
        r = o.handle("закрой хром")
        o.confirm(r["confirm"]["id"], accept=False)
        self.assertEqual(o.storage.events_for_day(date.today(), "done"), [])

    def test_confirmation_cannot_be_reused(self):
        o = make()
        pid = o.handle("закрой хром")["confirm"]["id"]
        o.confirm(pid, True)
        self.assertEqual(o.confirm(pid, True)["status"], "error")

    def test_untrusted_source_always_confirms(self):
        r = make().handle("открой калькулятор", source="message")
        self.assertEqual(r["status"], "confirm")

    def test_app_outside_whitelist_confirms(self):
        self.assertEqual(make().handle("открой regedit")["status"], "confirm")

    def test_killswitch_blocks_everything_until_resume(self):
        o = make()
        o.handle("стоп")
        self.assertEqual(o.handle("открой калькулятор")["status"], "stopped")
        self.assertEqual(o.handle("добавь задачу тест")["status"], "stopped")
        o.handle("продолжай")
        self.assertEqual(o.handle("открой калькулятор")["status"], "done")

    def test_task_keeps_original_spelling(self):
        o = make()
        o.handle("добавь задачу подготовить отчёт для Telegram-канала в 14:00")
        t = o.storage.tasks_for_day(date.today())[0]
        self.assertEqual(t["title"], "Подготовить отчёт для Telegram-канала")
        self.assertTrue(t["due_at"].endswith("14:00:00"))

    def test_complete_and_undo(self):
        o = make()
        o.handle("добавь задачу подготовить отчёт")
        o.handle("отметь подготовить отчет")
        self.assertEqual(o.storage.tasks_for_day(date.today())[0]["status"], "done")
        r = o.handle("отмени")
        self.assertEqual(r["status"], "done")
        self.assertEqual(o.storage.tasks_for_day(date.today())[0]["status"], "open")

    def test_undo_add_removes_task(self):
        o = make()
        o.handle("добавь задачу купить хлеб")
        o.handle("отмени")
        self.assertEqual(o.storage.tasks_for_day(date.today()), [])


class FakeLLM(LLMClient):
    """LLM, которая сначала отвечает с ошибкой, потом правильно."""
    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)

    def enabled(self):
        return True

    def _chat(self, messages, fmt=None):
        return self.answers.pop(0)


class LLMTest(unittest.TestCase):
    def test_retry_after_invalid_output(self):
        llm = FakeLLM(["не json", json.dumps({"steps": [{"tool": "day.add_task", "args": {"title": "кофе"}}]})])
        o = Orchestrator(Storage(), llm=llm, dry_run=True)
        self.assertEqual(o.handle("не забыть бы про кофе")["via"], "llm")

    def test_gives_up_honestly(self):
        llm = FakeLLM(["{}x", "{}x"])
        o = Orchestrator(Storage(), llm=llm, dry_run=True)
        self.assertEqual(o.handle("абракадабра")["status"], "unknown")

    def test_llm_cannot_call_hidden_or_system_tools(self):
        llm = FakeLLM([json.dumps({"steps": [{"tool": "day.delete_task", "args": {"task_id": 1}}]})] * 2)
        o = Orchestrator(Storage(), llm=llm, dry_run=True)
        self.assertEqual(o.handle("удали всё")["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
