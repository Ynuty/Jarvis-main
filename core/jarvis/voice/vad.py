"""
============================================================
 VAD — потоковый детектор речи на Silero v6 (ONNX из faster-whisper).
 Кадры по 512 сэмплов (32 мс при 16 кГц), состояние h/c сохраняется
 между кадрами. Сегментатор режет поток на фразы: преролл 300 мс,
 конец фразы — тишина end_ms, принудительный срез через max_s.
============================================================
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Callable

import numpy as np

SR = 16000
FRAME = 512
CONTEXT = 64


class SileroStream:
    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model
        self.session = get_vad_model().session
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.ctx = np.zeros((1, CONTEXT), dtype="float32")

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.ctx, frame.reshape(1, FRAME)], axis=1)
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.ctx = frame[-CONTEXT:].reshape(1, CONTEXT)
        return float(np.asarray(out).reshape(-1)[0])


class EnergyVAD:
    """Запасной детектор по энергии — если ONNX недоступен (и в тестах)."""

    def __init__(self) -> None:
        self.floor = 0.005

    def reset(self) -> None:
        pass

    def __call__(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        if rms < self.floor * 2:
            self.floor = 0.95 * self.floor + 0.05 * rms
        return min(1.0, max(0.0, (rms / max(self.floor, 1e-4) - 2.0) / 4.0))


@dataclass
class VadOptions:
    threshold: float = 0.5
    start_frames: int = 3          # ~96 мс речи подряд — начало фразы
    end_ms: int = 550              # тишина, после которой фраза закончена
    preroll_ms: int = 300
    max_s: float = 15.0
    min_speech_ms: int = 250


class Segmenter:
    """
    Принимает PCM16 любыми кусками, выдаёт события:
      on_start()                    — началась речь
      on_partial(audio: float32)    — каждые ~0,8 с во время речи (для живой расшифровки)
      on_segment(audio: float32)    — фраза закончилась
    """

    def __init__(self, model=None, opts: VadOptions | None = None,
                 on_start: Callable[[], None] | None = None,
                 on_partial: Callable[[np.ndarray], None] | None = None,
                 on_segment: Callable[[np.ndarray], None] | None = None,
                 on_level: Callable[[float], None] | None = None) -> None:
        self.model = model or _default_model()
        self.o = opts or VadOptions()
        self.on_start, self.on_partial, self.on_segment, self.on_level = on_start, on_partial, on_segment, on_level
        self.buf = np.zeros(0, dtype="float32")
        self.pre = collections.deque(maxlen=max(1, self.o.preroll_ms * SR // 1000 // FRAME))
        self.speech: list[np.ndarray] = []
        self.active = False
        self.hits = 0
        self.silence = 0
        self.since_partial = 0
        self.threshold = self.o.threshold

    def reset(self) -> None:
        self.buf = np.zeros(0, dtype="float32")
        self.pre.clear()
        self.speech = []
        self.active = False
        self.hits = self.silence = self.since_partial = 0
        self.model.reset()

    def feed_pcm16(self, data: bytes) -> None:
        pcm = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
        self.feed(pcm)

    def feed(self, pcm: np.ndarray) -> None:
        self.buf = np.concatenate([self.buf, pcm])
        while len(self.buf) >= FRAME:
            frame, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            self._frame(frame)

    def _frame(self, frame: np.ndarray) -> None:
        p = self.model(frame)
        if self.on_level:
            self.on_level(float(np.sqrt(np.mean(frame ** 2))))
        speaking = p >= self.threshold
        if not self.active:
            self.pre.append(frame)
            self.hits = self.hits + 1 if speaking else 0
            if self.hits >= self.o.start_frames:
                self.active = True
                self.speech = list(self.pre)
                self.silence = 0
                self.since_partial = 0
                if self.on_start:
                    self.on_start()
            return

        self.speech.append(frame)
        self.since_partial += 1
        self.silence = 0 if p >= self.threshold - 0.15 else self.silence + 1
        dur = len(self.speech) * FRAME / SR
        if self.on_partial and self.since_partial * FRAME >= int(0.8 * SR):
            self.since_partial = 0
            self.on_partial(np.concatenate(self.speech))
        if self.silence * FRAME * 1000 // SR >= self.o.end_ms or dur >= self.o.max_s:
            audio = np.concatenate(self.speech)
            voiced = (len(self.speech) - self.silence) * FRAME * 1000 // SR
            self.active = False
            self.speech = []
            self.hits = 0
            self.pre.clear()
            if voiced >= self.o.min_speech_ms and self.on_segment:
                self.on_segment(audio)


def _default_model():
    try:
        return SileroStream()
    except Exception:  # noqa: BLE001
        return EnergyVAD()
