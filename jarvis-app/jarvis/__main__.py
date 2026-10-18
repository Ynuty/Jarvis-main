"""Запуск: python -m jarvis [--dry-run] [--no-window] [--port 8765]"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from .core import Orchestrator
from .llm import LLMClient
from .resources import PROFILES, ModelManager, suggest_profile
from .server import App, serve
from .storage import Storage


def data_dir() -> Path:
    if os.environ.get("JARVIS_DATA_DIR"):
        return Path(os.environ["JARVIS_DATA_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Jarvis"
    return Path.home() / ".jarvis"


def main() -> None:
    p = argparse.ArgumentParser(prog="jarvis", description="Джарвис — локальный помощник")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--dry-run", action="store_true", help="ничего не делать в системе, только журнал")
    p.add_argument("--no-window", action="store_true", help="не открывать окно, только сервер")
    p.add_argument("--no-llm", action="store_true", help="только роутер правил")
    p.add_argument("--ollama", default=os.environ.get("JARVIS_OLLAMA", "http://127.0.0.1:11434"))
    args = p.parse_args()

    ddir = data_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    storage = Storage(ddir / "jarvis.db")

    # Профиль выбирается при первом запуске по объёму памяти.
    profile = storage.get_setting("profile", scope="device")
    if profile not in PROFILES:
        profile = suggest_profile()
        storage.set_setting("profile", profile, scope="device")
    models = ModelManager(profile)
    llm = None if args.no_llm else LLMClient(args.ollama, os.environ.get("JARVIS_LLM_MODEL", PROFILES[profile]["llm"]))

    orchestrator = Orchestrator(storage, llm=llm, dry_run=args.dry_run)
    app = App(orchestrator, llm, models, ddir)

    port = args.port
    for attempt in range(10):
        try:
            httpd = serve(app, port + attempt)
            port += attempt
            break
        except OSError:
            continue
    else:
        sys.exit("Не удалось занять порт для ядра")

    # Прогреть Whisper заранее, чтобы первая голосовая команда не ждала загрузки.
    if app.stt_backend() == "local":
        threading.Thread(target=models.whisper, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"Джарвис запущен: {url}  (данные: {ddir}, профиль: {profile}"
          f"{', тестовый режим' if args.dry_run else ''})")

    if args.no_window:
        httpd.serve_forever()
        return

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        import webview  # type: ignore  # pywebview: отдельное окно без рамки браузера
        webview.create_window("Джарвис", url, width=1100, height=720, min_size=(720, 560),
                              background_color="#0E1116")
        webview.start()
    except ImportError:
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
