"""Озвучка ответа офлайн. Сейчас — pyttsx3 (SAPI5 на Windows, без интернета);
Silero / Piper подключаются сюда же, когда будет выбран голос."""
from __future__ import annotations

import threading

from .echo_guard import EchoGuard


class TTS:
    def __init__(self, guard: EchoGuard):
        self.guard = guard
        self._lock = threading.Lock()
        try:
            import pyttsx3  # type: ignore  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    def speak(self, text: str) -> None:
        if not self.available or not text:
            return
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text: str) -> None:
        import pyttsx3  # type: ignore
        with self._lock, self.guard.speaking():
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
