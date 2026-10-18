"""Распознавание речи локально через faster-whisper (Whisper на CTranslate2).

Аудио приходит от интерфейса после push-to-talk (Пробел зажат → отпущен).
Если пакет не установлен, голос честно недоступен, текстовый ввод работает.
"""
from __future__ import annotations

import os
import tempfile

from ..resources import ModelManager


class STTUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401  # type: ignore
        return True
    except ImportError:
        return False


def transcribe(models: ModelManager, audio: bytes, suffix: str = ".webm") -> str:
    if not available():
        raise STTUnavailable("Голос не настроен: установите пакет faster-whisper (см. README)")
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        segments, _ = models.whisper().transcribe(path, language="ru", vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        os.unlink(path)
