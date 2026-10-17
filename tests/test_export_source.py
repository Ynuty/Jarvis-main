from datetime import datetime

import pytest

from jarvis.sources.base import resolve_chats
from jarvis.sources.telegram_export import TelegramExportSource, flatten_text


def test_flatten_text_handles_entities():
    assert flatten_text("просто") == "просто"
    assert flatten_text(["a ", {"type": "bold", "text": "b"}, " c"]) == "a b c"
    assert flatten_text(None) == ""


def test_single_chat_export(single_export):
    src = TelegramExportSource(single_export, me="Саша")
    chats = src.list_chats()
    assert [(c.id, c.title, c.kind) for c in chats] == [("tg:1001", "Курсовой проект", "group")]

    msgs = list(src.iter_messages(["tg:1001"]))
    ids = [m.message_id for m in msgs]
    assert 1 not in ids          # служебное сообщение пропущено
    assert 6 not in ids          # фото без подписи пропущено
    assert ids == sorted(ids)
    by_id = {m.message_id: m for m in msgs}
    assert by_id[4].text == "Саша, подготовь, пожалуйста, слайды по рынку до пятницы"
    assert by_id[5].is_outgoing and by_id[5].reply_to == 4
    assert not by_id[4].is_outgoing


def test_full_export_detects_owner(full_export):
    src = TelegramExportSource(full_export)
    kinds = {c.title: c.kind for c in src.list_chats()}
    assert kinds == {"Ольга (заказчик)": "private", "Избранное": "saved"}
    msgs = {m.message_id: m for m in src.iter_messages(["tg:2002"])}
    assert msgs[101].is_outgoing is True     # владелец определён по personal_information
    assert msgs[100].is_outgoing is False


def test_since_filter(single_export):
    src = TelegramExportSource(single_export, me="Саша")
    msgs = list(src.iter_messages(["tg:1001"], since=datetime(2026, 10, 13)))
    assert {m.message_id for m in msgs} == {8, 9, 10, 11}


def test_resolve_chats_by_title_and_id(single_export):
    chats = TelegramExportSource(single_export).list_chats()
    assert resolve_chats(chats, ["курсовой проект"])[0].id == "tg:1001"
    assert resolve_chats(chats, ["1001"])[0].id == "tg:1001"
    with pytest.raises(LookupError):
        resolve_chats(chats, ["Чужой чат"])


def test_rejects_non_export(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        TelegramExportSource(bad)
