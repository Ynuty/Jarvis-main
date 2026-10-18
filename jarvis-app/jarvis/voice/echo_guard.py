"""Защита от эха: пока Джарвис говорит, микрофон «заглушён» — запись не принимается."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

TAIL = 0.4  # секунд после конца речи, пока затихает динамик


class EchoGuard:
    def __init__(self):
        self._until = 0.0
        self._active = threading.Event()

    @contextmanager
    def speaking(self):
        self._active.set()
        try:
            yield
        finally:
            self._active.clear()
            self._until = time.time() + TAIL

    @property
    def muted(self) -> bool:
        return self._active.is_set() or time.time() < self._until
