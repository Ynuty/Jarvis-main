"""Нормализация фразы и словарь синонимов (шаг 2 жизненного цикла команды)."""
from __future__ import annotations

import difflib
import re

# Разговорное название → каноническое. Сайты сразу превращаются в адрес,
# чтобы «открой ютуб» ушло в open_url, а не в open_app.
SYNONYMS: dict[str, str] = {
    # формы в родительном падеже — для «сверни всё, кроме хрома»
    "телеграмм": "telegram", "телеграм": "telegram", "телеграма": "telegram", "телеграмма": "telegram",
    "телегу": "telegram", "телега": "telegram", "телеги": "telegram", "тг": "telegram",
    "гугл хром": "chrome", "хром": "chrome", "хрома": "chrome", "google chrome": "chrome",
    "браузер": "browser", "браузера": "browser",
    "блокнот": "notepad", "блокнота": "notepad",
    "калькулятор": "calculator", "калькулятора": "calculator",
    "проводник": "explorer", "проводника": "explorer", "мой компьютер": "explorer", "папки": "explorer",
    "вс код": "vscode", "vs code": "vscode", "visual studio code": "vscode",
    "спотифай": "spotify", "спотифая": "spotify",
    "ворд": "word", "ворда": "word", "эксель": "excel", "экселя": "excel",
    "стим": "steam", "стима": "steam", "стиме": "steam",
    "сафари": "safari", "файндер": "finder",
    "ютуб": "youtube.com", "youtube": "youtube.com",
    "гугл": "google.com", "google": "google.com",
    "вконтакте": "vk.com", "вк": "vk.com",
    "яндекс": "ya.ru",
}

# Канонические имена программ (ключи APPS) — для нечёткого сравнения.
_KNOWN = sorted(set(v for v in SYNONYMS.values() if "." not in v) | {"telegram", "steam", "safari"})

FILLERS = re.compile(r"^(?:(?:джарвис|jarvis|эй|слушай|пожалуйста|будь добр|можешь)[\s,]+)+|[\s,]+пожалуйста$")
_SYN_RE = [
    (re.compile(rf"(?<![\w.]){re.escape(k)}(?![\w.])"), v)
    for k, v in sorted(SYNONYMS.items(), key=lambda kv: -len(kv[0]))
]


def normalize(text: str) -> str:
    t = text.lower().replace("ё", "е").strip()
    t = re.sub(r"[!?«»\"“”]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return FILLERS.sub("", t).strip(" ,")


def canon(name: str) -> str:
    """Название программы или сайта → каноническое («телеграм» → telegram).
    Применяется только к аргументам, чтобы не портить текст задач."""
    n = name.strip().lower()
    for rx, c in _SYN_RE:
        n = rx.sub(c, n)
    if n in _KNOWN:
        return n
    # Whisper может исказить окончание: «сафар» → safari, «телеграмм» и т.п.
    match = difflib.get_close_matches(n, list(SYNONYMS) + _KNOWN, n=1, cutoff=0.75)
    if match:
        return SYNONYMS.get(match[0], match[0])
    return n


def recover(fragment: str, original: str) -> str:
    """Вернуть фрагменту исходный регистр и «ё» из фразы пользователя."""
    words = [re.escape(w).replace("е", "[её]") for w in fragment.split()]
    if not words:
        return fragment
    m = re.search(r"\s+".join(words), original, re.IGNORECASE)
    return m.group(0) if m else fragment
