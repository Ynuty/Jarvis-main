"""Профили железа Lite / Standard / Pro и менеджер моделей.

LLM и Whisper вместе могут не поместиться в память, поэтому менеджер держит
загруженной одну тяжёлую модель распознавания и выгружает её при смене профиля.
"""
from __future__ import annotations

import os
import sys
import threading

PROFILES: dict[str, dict] = {
    "lite":     {"title": "Lite",     "whisper": "small",    "llm": "qwen2.5:3b-instruct",  "min_ram_gb": 8},
    "standard": {"title": "Standard", "whisper": "medium",   "llm": "qwen2.5:7b-instruct",  "min_ram_gb": 16},
    "pro":      {"title": "Pro",      "whisper": "large-v3", "llm": "qwen2.5:14b-instruct", "min_ram_gb": 32},
}


def total_ram_gb() -> float:
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, AttributeError):
        return 8.0


def suggest_profile() -> str:
    ram = total_ram_gb()
    return "pro" if ram >= 32 else "standard" if ram >= 16 else "lite"


class ModelManager:
    def __init__(self, profile: str):
        self.profile = profile if profile in PROFILES else "lite"
        self._whisper = None
        self._lock = threading.Lock()

    def set_profile(self, profile: str) -> None:
        with self._lock:
            if profile in PROFILES and profile != self.profile:
                self.profile = profile
                self._whisper = None  # выгрузить: загрузится заново под новый профиль

    def whisper(self):
        """Ленивая загрузка faster-whisper. Модель должна лежать на диске
        (офлайн-установка) или скачается один раз при первом запуске."""
        with self._lock:
            if self._whisper is None:
                from faster_whisper import WhisperModel  # type: ignore
                name = os.environ.get("JARVIS_WHISPER_MODEL", PROFILES[self.profile]["whisper"])
                self._whisper = WhisperModel(name, device="auto", compute_type="int8")
            return self._whisper
