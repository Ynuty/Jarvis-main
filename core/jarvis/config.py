"""
============================================================
 Конфиг — пути, профили железа, настройки по умолчанию.
 Данные пользователя живут в %APPDATA%/Jarvis (или $JARVIS_HOME),
 модели — в подпапке models/. Код в репозитории ничего не хранит.
============================================================
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    if env := os.environ.get("JARVIS_HOME"):
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Jarvis"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Jarvis"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jarvis"


HOME = _default_home()
MODELS = HOME / "models"
DB_PATH = HOME / "jarvis.db"
PACKAGE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = PACKAGE_DIR / "llm" / "prompts"

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_PORT", "8777"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# Общий секрет оболочки и ядра: без него чужая страница в браузере
# не сможет дёрнуть localhost-API (защита от CSRF и DNS-rebinding).
LAUNCH_SECRET = os.environ.get("JARVIS_SECRET", "")


@dataclass(frozen=True)
class HardwareProfile:
    id: str
    title: str
    whisper: str
    llm: str
    note: str


PROFILES = {
    "lite": HardwareProfile("lite", "Лёгкий", "base", "qwen2.5:1.5b", "без видеокарты, 8 ГБ ОЗУ"),
    "standard": HardwareProfile("standard", "Стандартный", "small", "qwen2.5:7b", "видеокарта от 6 ГБ или Apple Silicon"),
    "max": HardwareProfile("max", "Максимальный", "medium", "qwen2.5:7b", "видеокарта от 10 ГБ"),
}

# Настройки профиля пользователя по умолчанию. Всё, что не секрет.
DEFAULT_SETTINGS: dict = {
    "address_as": "сэр",
    "timezone": "Europe/Moscow",
    "city": "Москва",
    "language": "ru",
    "hw_profile": "standard",
    "whisper_model": "small",
    "whisper_device": "auto",
    "llm_model": "qwen2.5:7b",
    "llm_temperature": 0.6,
    "llm_ctx_turns": 8,
    "embed_model": "nomic-embed-text",
    "tts_engine": "piper",
    "tts_voice": "ru_RU-denis-medium",
    "tts_rate": 1.0,
    "listen_mode": "wake",          # wake | open | ptt
    "mic_device": "",
    "wake_word": "джарвис",
    "theme": "hud",
    "accent": "#5ad9ff",
    "hotkey_global": "Control+Alt+J",
    "autostart": False,
    "default_shop": "",
    "addresses": [],
    "favorites": [],
    "mail_rules": [],
    "collect_dataset": False,
    "web_search": True,             # инструмент есть, но вызывается только по явной просьбе
}


def ensure_dirs() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
