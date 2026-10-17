from jarvis.core.sync import sync
from jarvis.day.extractor import Identity, TaskExtractor
from jarvis.models import STATUS_DONE
from jarvis.sources.telegram_export import TelegramExportSource
from jarvis.storage.db import Database


def test_sync_is_idempotent(tmp_path, single_export):
    db = Database(tmp_path / "j.db")
    src = TelegramExportSource(single_export, me="Саша")
    chats = src.list_chats()

    first = sync(src, chats, TaskExtractor(me=Identity(("Саша",))), db)
    assert first.messages_new == 9 and len(first.tasks_new) >= 2

    second = sync(src, chats, TaskExtractor(me=Identity(("Саша",))), db)
    assert second.messages_new == 0 and second.tasks_new == []
    assert len(db.list_tasks()) == len(first.tasks_new)


def test_status_and_journal(tmp_path, full_export):
    db = Database(tmp_path / "j.db")
    src = TelegramExportSource(full_export)
    result = sync(src, src.list_chats(), TaskExtractor(), db)
    task = result.tasks_new[0]

    assert db.set_status(task.id, STATUS_DONE)
    assert task.id not in [t.id for t in db.list_tasks()]
    assert task.id in [t.id for t in db.list_tasks(status=None)]

    kinds = [e["kind"] for e in db.list_events()]
    assert "sync_started" in kinds and "sync_finished" in kinds and "task_found" in kinds


def test_tasks_sorted_by_due(tmp_path, single_export, full_export):
    db = Database(tmp_path / "j.db")
    for path, me in ((single_export, "Саша"), (full_export, None)):
        src = TelegramExportSource(path, me=me)
        sync(src, src.list_chats(), TaskExtractor(me=Identity(("Саша",))), db)
    dues = [t.due_at for t in db.list_tasks()]
    with_due = [d for d in dues if d is not None]
    assert with_due == sorted(with_due)
    assert dues[: len(with_due)] == with_due     # задачи без срока — в конце
