"""Запуск ядра: python -m jarvis [--port N]. Оболочка передаёт JARVIS_SECRET через окружение."""
import argparse
import logging
import os
import sys

import uvicorn

from . import config


def main() -> None:
    ap = argparse.ArgumentParser(prog="jarvis-core")
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--log", default=os.environ.get("JARVIS_LOG", "info"))
    ap.add_argument("--probe-cuda", metavar="MODEL", help="служебное: проверить Whisper на CUDA и выйти")
    a = ap.parse_args()
    if a.probe_cuda:
        from .voice.stt import probe_cuda_main
        sys.exit(probe_cuda_main(a.probe_cuda))
    config.ensure_dirs()
    logging.basicConfig(level=a.log.upper(), format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(config.HOME / "core.log", encoding="utf-8")])
    # Ядро не ходит в сеть само: HF-загрузчики Whisper включаются только из мастера.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    from .api.server import app
    print(f"JARVIS_CORE_READY {a.port}", flush=True)
    uvicorn.run(app, host=config.HOST, port=a.port, log_level="warning", ws_max_size=4 * 1024 * 1024)


if __name__ == "__main__":
    main()
