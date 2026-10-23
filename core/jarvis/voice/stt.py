"""
============================================================
 STT — faster-whisper, русский. Сначала пробуем CUDA (float16),
 при любой ошибке — CPU int8. Модель грузится один раз и
 «прогревается» тишиной, чтобы первая фраза не ждала инициализации.
 hotwords — имена приложений, магазинов и «Джарвис»: заметно
 поднимает точность имён собственных.
============================================================
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .. import config

log = logging.getLogger("jarvis.stt")

HOTWORDS = ("Джарвис, таймер, напомни, заметки, корзина, закажи, почта, задача, "
            "Пятёрочка, Перекрёсток, ВкусВилл, Самокат, Яндекс Лавка, Telegram, Chrome")


def _add_cuda_dlls() -> None:
    """pip-пакеты nvidia-cublas/cudnn кладут DLL в site-packages/nvidia/*/bin."""
    if sys.platform != "win32":
        return
    for base in sys.path:
        root = Path(base) / "nvidia"
        if root.is_dir():
            for bin_dir in root.glob("*/bin"):
                try:
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                except OSError:
                    pass


class STT:
    def __init__(self, model: str = "small", device: str = "auto") -> None:
        self.model_name = model
        self.device_pref = device
        self.model = None
        self.device = "?"
        self.lock = threading.Lock()
        self.error = ""

    def load(self) -> bool:
        from faster_whisper import WhisperModel
        _add_cuda_dlls()
        root = str(config.MODELS / "whisper")
        tries = []
        if self.device_pref in ("auto", "cuda"):
            tries.append(("cuda", "float16"))
        if self.device_pref in ("auto", "cpu"):
            tries.append(("cpu", "int8"))
        for device, ctype in tries:
            try:
                # local_files_only: никаких фоновых загрузок — модель качает только мастер по кнопке
                m = WhisperModel(self.model_name, device=device, compute_type=ctype, download_root=root,
                                 local_files_only=True)
                # прогрев: на CUDA именно здесь всплывают отсутствующие DLL
                list(m.transcribe(np.zeros(16000, dtype="float32"), language="ru", beam_size=1)[0])
                self.model, self.device = m, f"{device}/{ctype}"
                log.info("whisper %s на %s", self.model_name, self.device)
                return True
            except Exception as e:  # noqa: BLE001
                self.error = f"{device}: {e}"
                log.warning("whisper %s на %s не поднялся: %s", self.model_name, device, e)
        return False

    @property
    def ready(self) -> bool:
        return self.model is not None

    def transcribe(self, audio: np.ndarray, hotwords: str = "", fast: bool = False) -> tuple[str, float]:
        """Возвращает (текст, секунды на распознавание)."""
        if not self.model:
            return "", 0.0
        t0 = time.perf_counter()
        with self.lock:
            segs, _info = self.model.transcribe(
                audio, language="ru", task="transcribe",
                beam_size=1 if fast else 3,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
                hotwords=(HOTWORDS + (", " + hotwords if hotwords else "")) if not fast else None,
                no_speech_threshold=0.6,
            )
            text = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.8).strip()
        return _clean(text), time.perf_counter() - t0


# Галлюцинации Whisper на тишине и шуме — известный список.
_HALLUCINATIONS = (
    "продолжение следует", "субтитры", "редактор субтитров", "спасибо за просмотр",
    "подписывайтесь на канал", "dimatorzok", "корректор",
)


def _clean(text: str) -> str:
    low = text.lower()
    if any(h in low for h in _HALLUCINATIONS) and len(low) < 80:
        return ""
    return text
