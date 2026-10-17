from datetime import datetime

import pytest

from jarvis.day.candidates import score_message
from jarvis.models import Message


def msg(text, outgoing=False):
    return Message("tg:1", 1, datetime(2026, 10, 12, 12, 0), "Анна", "user1", text, None, outgoing)


@pytest.mark.parametrize(
    "text",
    [
        "Скинь, пожалуйста, таблицу",
        "Подготовьте отчёт до пятницы",
        "Нужно оплатить счёт завтра",
        "Можешь проверить презентацию?",
        "Напомни Илье про созвон",
    ],
)
def test_requests_are_candidates(text):
    cand = score_message(msg(text))
    assert cand is not None and cand.kind == "request"


@pytest.mark.parametrize(
    "text",
    ["ок", "Спасибо!", "Ахаха, классный мем 😂", "Как дела у всех?", "Всем привет", "👍👍"],
)
def test_chatter_is_not_candidate(text):
    assert score_message(msg(text)) is None


def test_own_commitment():
    cand = score_message(msg("Пришлю завтра утром", outgoing=True))
    assert cand is not None and cand.kind == "commitment"


def test_own_message_without_commitment_is_ignored():
    assert score_message(msg("Скиньте мне потом ссылку", outgoing=True)) is None


def test_saved_messages_note():
    cand = score_message(msg("Не забыть оплатить хостинг", outgoing=True), self_note=True)
    assert cand is not None
