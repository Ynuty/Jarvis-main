"""
============================================================
 Менеджер моделей: Whisper, TTS, Ollama — общие для всех профилей.
 Тяжёлые модели грузятся в фоне, интерфейс сразу видит статус
 («загружается», «готово», «ошибка: …») и работает текстом,
 пока голос не готов. Сбой модели не роняет ядро.
============================================================
"""
from __future__ import annotations

import asyncio
import logging
import threading

from . import config
from .llm.ollama import Ollama
from .voice.stt import STT
from .voice.tts import TTS

log = logging.getLogger("jarvis.engines")


class Engines:
    def __init__(self) -> None:
        self.stt: STT | None = None
        self.tts: TTS | None = None
        self.ollama = Ollama()
        self.status = {"stt": "не загружен", "tts": "не загружен", "llm": "не проверен"}
        self.llm_ok = False
        self.llm_model = ""
        self._lock = threading.Lock()
        self.listeners: list = []          # сессии: сообщить окнам, что модель догрузилась
        self.tts_loading = False

    def changed(self) -> None:
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    # ---------- голос ----------

    def load_voice(self, settings: dict, *, background: bool = True) -> None:
        def work():
            with self._lock:
                # голос первым: Piper грузится за доли секунды, а ответить голосом нужно сразу
                want_tts = (settings.get("tts_engine"), settings.get("tts_voice"))
                if not self.tts or not self.tts.ready or (self.tts.engine_pref, self.tts.voice_name) != want_tts:
                    self.status["tts"] = "загружается"
                    self.tts_loading = True
                    tts = TTS(*want_tts, rate=float(settings.get("tts_rate", 1.0)))
                    ok = tts.load()
                    self.tts = tts
                    self.tts_loading = False
                    self.status["tts"] = f"готово ({tts.engine}, {tts.voice_name})" if ok else \
                        f"запасной голос интерфейса ({tts.error[:100]})"
                    log.info("tts: %s", self.status["tts"])
                    self.changed()
                elif self.tts:
                    self.tts.rate = float(settings.get("tts_rate", 1.0))
                self.tts_loading = False
                want_stt = (settings.get("whisper_model"), settings.get("whisper_device"))
                if not self.stt or not self.stt.ready or (self.stt.model_name, self.stt.device_pref) != want_stt:
                    self.status["stt"] = "загружается"
                    self.changed()
                    stt = STT(*want_stt)
                    ok = stt.load()
                    self.stt = stt
                    self.status["stt"] = f"готово ({stt.model_name}, {stt.device})" if ok else f"ошибка: {stt.error[:120]}"
            self.changed()

        self.tts_loading = True           # сразу: фраза, сказанная до старта потока, тоже подождёт голос
        if background:
            threading.Thread(target=work, name="voice-load", daemon=True).start()
        else:
            work()

    # ---------- LLM ----------

    async def check_llm(self, model: str) -> bool:
        if not await self.ollama.alive():
            self.status["llm"] = "Ollama не запущена"
            self.llm_ok = False
            return False
        if not await self.ollama.has_model(model):
            self.status["llm"] = f"модель {model} не скачана"
            self.llm_ok = False
            return False
        self.llm_ok, self.llm_model = True, model
        self.status["llm"] = f"готово ({model})"
        self.changed()
        asyncio.create_task(self._warm(model))
        return True

    async def _warm(self, model: str) -> None:
        try:
            await self.ollama.warm(model)
        except Exception as e:  # noqa: BLE001
            log.warning("прогрев %s: %s", model, e)


engines = Engines()


def hw_detect() -> dict:
    """Автоопределение профиля железа для мастера первого запуска."""
    import os
    import subprocess
    info = {"gpu": "", "vram_mb": 0, "ram_gb": 0.0, "cpus": os.cpu_count() or 1, "profile": "lite"}
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            name, mem = out.stdout.strip().splitlines()[0].rsplit(",", 1)
            info["gpu"], info["vram_mb"] = name.strip(), int(mem.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
        info["ram_gb"] = round(m.ullTotalPhys / 2**30, 1)
    except (AttributeError, OSError):
        pass
    if info["vram_mb"] >= 10000:
        info["profile"] = "max"
    elif info["vram_mb"] >= 6000:
        info["profile"] = "standard"
    else:
        info["profile"] = "lite"
    p = config.PROFILES[info["profile"]]
    info.update(whisper=p.whisper, llm=p.llm, title=p.title)
    return info
