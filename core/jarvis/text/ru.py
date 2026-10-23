"""
============================================================
 Русский текст: нормализация, числительные, склонение,
 длительности, калькулятор без eval, лемматизация (pymorphy3).
 Перенос утилит из js/brain.js с доработками.
============================================================
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

# ---------- нормализация ----------

_PUNCT = re.compile(r"[«»\"“”„.!?…]")


def norm(s: str | None) -> str:
    """Нижний регистр, ё → е, без конечной пунктуации, одиночные пробелы."""
    s = (s or "").lower().replace("ё", "е")
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"(?<!\d),|,(?!\d)", " , ", s)       # «10,5» и «15:30» не трогаем
    s = re.sub(r"(?<!\d):|:(?!\d)", " : ", s)
    s = re.sub(r"\s+([,:])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- числительные ----------

NUM: dict[str, float] = {
    "ноль": 0, "нуля": 0,
    "один": 1, "одна": 1, "одну": 1, "одно": 1, "одного": 1, "одной": 1,
    "полтора": 1.5, "полторы": 1.5,
    "два": 2, "две": 2, "двух": 2, "три": 3, "трех": 3, "четыре": 4, "четырех": 4,
    "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9, "десять": 10, "десяти": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "пятнадцати": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "двадцати": 20, "тридцать": 30, "тридцати": 30, "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "ста": 100,
    "двести": 200, "двухсот": 200, "триста": 300, "трехсот": 300, "четыреста": 400, "четырехсот": 400,
    "пятьсот": 500, "пятисот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_THOUSAND = {"тысяча", "тысячу", "тысячи", "тысяч"}


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def words2num(text: str) -> str:
    """«двадцать пять минут» → «25 минут», «две тысячи сто» → «2100»."""
    out: list[str] = []
    acc: float | None = None
    big = 0.0
    for w in text.split(" "):
        if w in NUM:
            acc = (acc or 0) + NUM[w]
        elif w in _THOUSAND:
            big += (acc if acc is not None else 1) * 1000
            acc = 0
        else:
            if acc is not None or big:
                out.append(_fmt(big + (acc or 0)))
                acc, big = None, 0.0
            out.append(w)
    if acc is not None or big:
        out.append(_fmt(big + (acc or 0)))
    return " ".join(out)


def plural(n: float, one: str, few: str, many: str) -> str:
    a = abs(round(n)) % 100
    b = a % 10
    if 10 < a < 20:
        return many
    if 1 < b < 5:
        return few
    if b == 1:
        return one
    return many


def num(n: float) -> str:
    """Число по-русски: десятичная запятая, без лишних нулей."""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return str(n).replace(".", ",")


# ---------- время ----------

DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def part_of_day(h: int) -> str:
    if h < 5:
        return "Доброй ночи"
    if h < 12:
        return "Доброе утро"
    if h < 18:
        return "Добрый день"
    return "Добрый вечер"


_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек\b|минут\w*|мин\b|час\w*|ч\b)")


def parse_duration(src: str) -> int:
    """«две с половиной минуты», «полчаса», «90 секунд» → секунды. 0 — не понял."""
    s = words2num(src)
    s = re.sub(r"(\d+) с половиной (минут\w*|час\w*|секунд\w*)", lambda m: f"{m[1]}.5 {m[2]}", s)
    total, found = 0.0, False
    if "полчаса" in s:
        total += 1800; found = True
    if "полминуты" in s:
        total += 30; found = True
    if re.search(r"\bчас\b", s) and not re.search(r"\d+(?:[.,]\d+)?\s*час", s):
        total += 3600; found = True         # «через час»
    if re.search(r"\bминуту\b", s) and not re.search(r"\d+\s*минуту", s):
        total += 60; found = True           # «через минуту»
    for m in _DUR.finditer(s):
        v = float(m[1].replace(",", "."))
        u = m[2]
        total += v if u.startswith("сек") else v * 60 if u.startswith("мин") else v * 3600
        found = True
    if not found:
        bare = re.search(r"\d+(?:[.,]\d+)?", s)
        if bare:                             # «таймер на 5» = минуты
            total = float(bare[0].replace(",", ".")) * 60
            found = True
    return round(total) if found else 0


def human_duration(sec: int) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    parts = []
    if h:
        parts.append(f"{h} {plural(h, 'час', 'часа', 'часов')}")
    if m:
        parts.append(f"{m} {plural(m, 'минута', 'минуты', 'минут')}")
    if s:
        parts.append(f"{s} {plural(s, 'секунда', 'секунды', 'секунд')}")
    return " ".join(parts) or "0 секунд"


# ---------- калькулятор (свой парсер, без eval) ----------

def to_expr(src: str) -> str:
    s = words2num(norm(src))
    # деление раньше умножения: иначе «разделить на 8» съест правило «на перед числом»
    rules = [
        (r"\bплюс\b|\bприбавить\b|\bсложить\b|\bи еще\b", "+"),
        (r"\bминус\b|\bвычесть\b|\bотнять\b", "-"),
        (r"\bразделить на\b|\bподелить на\b|\bделить на\b|\bделенное на\b", "/"),
        (r"\bумножить на\b|\bумноженное на\b|\bумножь на\b|\bна\b(?=\s*\d)", "*"),
        (r"\bв квадрате\b", "^2"),
        (r"\bв кубе\b", "^3"),
        (r"\bв степени\b", "^"),
    ]
    for pat, rep in rules:
        s = re.sub(pat, rep, s)
    return s


_OPS = {"+": (1, "l"), "-": (1, "l"), "*": (2, "l"), "/": (2, "l"), "^": (3, "r")}


def calc(src: str) -> float | None:
    toks = re.findall(r"\d+(?:\.\d+)?|[+\-*/^()]", src.replace(",", "."))
    if not toks or not any(re.match(r"\d", t) for t in toks) or not any(t in _OPS for t in toks):
        return None
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def prim():
        nonlocal pos
        t = peek()
        if t == "(":
            pos += 1
            v = expr(0)
            if peek() == ")":
                pos += 1
            return v
        if t == "-":
            pos += 1
            v = prim()
            return None if v is None else -v
        pos += 1
        try:
            return float(t) if t is not None else None
        except ValueError:
            return None

    def expr(min_prec: int):
        nonlocal pos
        lhs = prim()
        while True:
            op = peek()
            info = _OPS.get(op or "")
            if not info or info[0] < min_prec:
                break
            pos += 1
            rhs = expr(info[0] + 1 if info[1] == "l" else info[0])
            if lhs is None or rhs is None:
                return None
            if op == "+":
                lhs = lhs + rhs
            elif op == "-":
                lhs = lhs - rhs
            elif op == "*":
                lhs = lhs * rhs
            elif op == "/":
                if rhs == 0:
                    return None
                lhs = lhs / rhs
            else:
                try:
                    lhs = math.pow(lhs, rhs)
                except (OverflowError, ValueError):
                    return None
        return lhs

    v = expr(0)
    if not isinstance(v, float) or not math.isfinite(v):
        return None
    return round(v * 1e6) / 1e6


# ---------- морфология ----------

@lru_cache(maxsize=1)
def _morph():
    import pymorphy3
    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=4096)
def lemma(word: str) -> str:
    """Начальная форма слова: «Пете» → «петя», «яиц» → «яйцо»."""
    if not word or not re.match(r"[а-яё]", word):
        return word
    return _morph().parse(word)[0].normal_form.replace("ё", "е")


_PROPER = {"Surn", "Name", "Patr", "Geox", "Orgn", "Abbr"}


def _best_parse(m, word: str):
    """Первый разбор, но не имя/фамилия: «лимонов» — это лимоны, а не писатель."""
    ps = m.parse(word)
    for p in ps:
        if not (_PROPER & set(p.tag.grammemes)):
            return p
    return ps[0]


def nominative(phrase: str, plural_form: bool | None = None) -> str:
    """
    Ставит словосочетание в именительный падеж: «свежего молока» → «свежее молоко»,
    «два десятка яиц» после выделения количества → «яйца».
    Главное слово — первое существительное; прилагательные согласуются с ним.
    """
    m = _morph()
    words = phrase.split()
    parses = [_best_parse(m, w) for w in words]
    head_i = next((i for i, p in enumerate(parses) if "NOUN" in p.tag), None)
    if head_i is None:
        return phrase
    head = parses[head_i]
    want_plur = head.tag.number == "plur" if plural_form is None else plural_form
    # «яиц», «яблок» (gent plur) — продукты исчисляемые, ставим во мн. ч.
    if plural_form is None and head.tag.case == "gent" and head.tag.number == "plur":
        want_plur = True
    out = []
    for i, (w, p) in enumerate(zip(words, parses)):
        if i < head_i and ("ADJF" in p.tag or "PRTF" in p.tag):
            gram = {"nomn", "plur"} if want_plur else {"nomn", head.normalized.tag.gender or "neut", "sing"}
            f = p.inflect(gram)
            out.append(f.word if f else w)
        elif i == head_i:
            f = head.normalized.inflect({"nomn", "plur"}) if want_plur else head.normalized
            out.append((f or head.normalized).word)
        elif i > head_i and i == head_i + 1 and "NOUN" in p.tag and p.tag.case == "gent":
            out.append(w)                    # «пачка масла» — зависимое слово не трогаем
        else:
            out.append(w)
    return " ".join(out).replace("ё", "е")
