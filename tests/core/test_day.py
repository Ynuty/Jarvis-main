"""Разбор времени задач «День»."""
import datetime as dt

from jarvis.skills.day import parse_when

NOW = dt.datetime(2026, 10, 21, 12, 0)   # среда


def when(text):
    title, ts = parse_when(text, NOW)
    return title, (dt.datetime.fromtimestamp(ts) if ts else None)


def test_time_today():
    assert when("созвон с командой в 15:00") == ("созвон с командой", dt.datetime(2026, 10, 21, 15, 0))


def test_tomorrow_morning():
    assert when("завтра в 9 утра позвонить маме") == ("позвонить маме", dt.datetime(2026, 10, 22, 9, 0))


def test_relative():
    assert when("через 2 часа выпить таблетку") == ("выпить таблетку", NOW + dt.timedelta(hours=2))


def test_evening_words():
    assert when("в семь вечера ужин") == ("ужин", dt.datetime(2026, 10, 21, 19, 0))


def test_weekday():
    assert when("в пятницу отчёт") == ("отчёт", dt.datetime(2026, 10, 23, 9, 0))


def test_no_time():
    assert when("купить подарок") == ("купить подарок", None)
