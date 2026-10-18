"""Словарь программ: каноническое имя → как запустить на каждой ОС.

Для Windows перечислены кандидаты по порядку: путь к exe, имя из App Paths,
протокол. Подходит первый сработавший.
"""
from __future__ import annotations

import os

APPS: dict[str, dict] = {
    "telegram": {
        "title": "Telegram",
        "win": [r"%APPDATA%\Telegram Desktop\Telegram.exe", "tg://"],
        "win_process": "telegram.exe",
        "mac": "Telegram",
    },
    "chrome": {"title": "Chrome", "win": ["chrome"], "win_process": "chrome.exe", "mac": "Google Chrome"},
    "browser": {"title": "браузер", "url": "about:blank"},
    "notepad": {"title": "Блокнот", "win": ["notepad"], "win_process": "notepad.exe", "mac": "TextEdit"},
    "calculator": {"title": "Калькулятор", "win": ["calc"], "win_process": "calculatorapp.exe", "mac": "Calculator"},
    "explorer": {"title": "Проводник", "win": ["explorer"], "win_process": "explorer.exe", "mac": "Finder"},
    "vscode": {"title": "VS Code", "win": ["code"], "win_process": "code.exe", "mac": "Visual Studio Code"},
    "spotify": {"title": "Spotify", "win": [r"%APPDATA%\Spotify\Spotify.exe", "spotify:"],
                "win_process": "spotify.exe", "mac": "Spotify"},
    "word": {"title": "Word", "win": ["winword"], "win_process": "winword.exe", "mac": "Microsoft Word"},
    "excel": {"title": "Excel", "win": ["excel"], "win_process": "excel.exe", "mac": "Microsoft Excel"},
    "steam": {"title": "Steam", "win": [r"%ProgramFiles(x86)%\Steam\steam.exe", "steam://open/main"],
              "win_process": "steam.exe", "mac": "Steam"},
    "safari": {"title": "Safari", "mac": "Safari"},
    "finder": {"title": "Finder", "mac": "Finder"},
}


def lookup(name: str) -> dict:
    key = name.lower().strip()
    if key in APPS:
        return {"key": key, **APPS[key]}
    # Неизвестная программа: пробуем запустить по имени как есть.
    return {"key": key, "title": name, "win": [name], "win_process": f"{key}.exe", "mac": name}


def expand(path: str) -> str:
    return os.path.expandvars(path)
