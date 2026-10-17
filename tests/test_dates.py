from datetime import datetime

import pytest

from jarvis.day.dates import parse_due

NOW = datetime(2026, 10, 12, 11, 30)  # понедельник


@pytest.mark.parametrize(
    "text, expected",
    [
        ("подготовь слайды до пятницы", datetime(2026, 10, 16, 23, 59)),
        ("скинь таблицу завтра к 18:00", datetime(2026, 10, 13, 18, 0)),
        ("загружу до 19.10", datetime(2026, 10, 19, 23, 59)),
        ("сдать до 20 октября", datetime(2026, 10, 20, 23, 59)),
        ("через 2 дня", datetime(2026, 10, 14, 23, 59)),
        ("через неделю", datetime(2026, 10, 19, 23, 59)),
        ("послезавтра", datetime(2026, 10, 14, 23, 59)),
        ("до конца недели", datetime(2026, 10, 16, 23, 59)),
        ("до конца месяца", datetime(2026, 10, 31, 23, 59)),
        ("в пн созвон", datetime(2026, 10, 19, 23, 59)),       # сегодня пн → следующий
        ("созвон в 7 вечера", datetime(2026, 10, 12, 19, 0)),
        ("к 18:00", datetime(2026, 10, 12, 18, 0)),
        ("в 9 утра", datetime(2026, 10, 13, 9, 0)),           # 9 утра уже прошло → завтра
        ("к 10.01", datetime(2027, 1, 10, 23, 59)),           # дата в прошлом → следующий год
        ("Завтра в 10:30", datetime(2026, 10, 13, 10, 30)),
    ],
)
def test_parse_due(text, expected):
    due = parse_due(text, NOW)
    assert due is not None, text
    assert due.at == expected


@pytest.mark.parametrize("text", ["просто текст", "у нас 3 задачи", "версия 2.0 вышла", ""])
def test_no_due(text):
    assert parse_due(text, NOW) is None
