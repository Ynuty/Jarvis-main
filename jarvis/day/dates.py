"""Разбор сроков на русском относительно даты сообщения.

Срок считаем сами, а не просим модель: маленькие модели плохо считают даты.
Если время не указано, срок — конец дня (23:59).
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

END_OF_DAY = time(23, 59)

_WEEKDAYS = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "сред": 2, "ср": 2,
    "четверг": 3, "чт": 3,
    "пятниц": 4, "пт": 4,
    "суббот": 5, "сб": 5,
    "воскресень": 6, "вс": 6,
}

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

_NUM_WORDS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}


@dataclass(frozen=True)
class Due:
    at: datetime
    text: str


def _next_weekday(base: date, weekday: int) -> date:
    """Ближайший такой день недели строго после base."""
    days = (weekday - base.weekday()) % 7
    return base + timedelta(days=days or 7)


def _find_time(text: str) -> tuple[time | None, str | None]:
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return time(int(m.group(1)), int(m.group(2))), m.group(0)
    m = re.search(r"\b(?:в|к|до)\s+(\d{1,2})\s*(утра|дня|вечера|ч\b|час)", text)
    if m:
        hour = int(m.group(1))
        part = m.group(2)
        if part in ("дня", "вечера") and hour < 12:
            hour += 12
        if 0 <= hour <= 23:
            return time(hour, 0), m.group(0)
    return None, None


def _find_date(text: str, base: date) -> tuple[date | None, str | None]:
    t = text

    m = re.search(r"\bпослезавтра\b", t)
    if m:
        return base + timedelta(days=2), m.group(0)
    m = re.search(r"\bзавтра\b", t)
    if m:
        return base + timedelta(days=1), m.group(0)
    m = re.search(r"\b(сегодня|до конца дня)\b", t)
    if m:
        return base, m.group(0)

    m = re.search(r"\bчерез\s+(\d+|один|одну|два|две|три|четыре|пять)?\s*(дн\w*|день|недел\w*)", t)
    if m:
        raw_n = m.group(1)
        n = 1 if raw_n is None else (int(raw_n) if raw_n.isdigit() else _NUM_WORDS[raw_n])
        unit_days = 7 if m.group(2).startswith("недел") else 1
        return base + timedelta(days=n * unit_days), m.group(0)

    m = re.search(r"\bдо конца недели\b", t)
    if m:
        friday = base + timedelta(days=(4 - base.weekday()) % 7)
        return friday, m.group(0)
    m = re.search(r"\bдо конца месяца\b", t)
    if m:
        last = monthrange(base.year, base.month)[1]
        return base.replace(day=last), m.group(0)

    # 20.10 или 20.10.2026 (не путаем со временем 18:00)
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = m.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            y = int(year) + (2000 if year and len(year) == 2 else 0) if year else base.year
            try:
                d = date(y, month, day)
            except ValueError:
                d = None
            if d is not None:
                if not year and d < base - timedelta(days=60):
                    d = d.replace(year=d.year + 1)  # «до 10.01», сказанное в декабре
                return d, m.group(0)

    # 20 октября
    m = re.search(r"\b(\d{1,2})\s+(январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", t)
    if m:
        day = int(m.group(1))
        stem = m.group(2)
        month = _MONTHS["ма"] if stem.startswith("ма") and stem != "март" else _MONTHS[stem]
        try:
            d = date(base.year, month, day)
        except ValueError:
            d = None
        if d is not None:
            if d < base - timedelta(days=60):
                d = d.replace(year=d.year + 1)
            return d, m.group(0)

    # до пятницы, к среде, в понедельник, в пт
    m = re.search(
        r"\b(?:до|к|в|во|на)\s+(понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*|пн|вт|ср|чт|пт|сб|вс)\b",
        t,
    )
    if m:
        word = m.group(1)
        for stem, wd in _WEEKDAYS.items():
            if word.startswith(stem):
                return _next_weekday(base, wd), m.group(0)

    return None, None


def parse_due(text: str, now: datetime) -> Due | None:
    """Находит срок в тексте. now — дата сообщения, от неё считаем «завтра» и т. п."""
    t = text.casefold().replace("ё", "е")
    d, d_text = _find_date(t, now.date())
    tm, tm_text = _find_time(t)
    if d is None and tm is None:
        return None
    if d is None:
        # указано только время: сегодня, а если оно уже прошло — завтра
        d = now.date() if datetime.combine(now.date(), tm) >= now else now.date() + timedelta(days=1)
    at = datetime.combine(d, tm or END_OF_DAY)
    pieces = [p for p in (d_text, tm_text) if p]
    return Due(at=at, text=" ".join(pieces))
