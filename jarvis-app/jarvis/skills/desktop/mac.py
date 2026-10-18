"""macOS: запасной бэкенд для разработки и проверки вне Windows."""
from __future__ import annotations

import subprocess


def _osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise OSError(r.stderr.strip())
    return r.stdout.strip()


def windows(include_minimized: bool = False) -> list[dict]:
    names = _osa('tell application "System Events" to get name of every process '
                 'whose background only is false and visible is true')
    return [{"title": n, "process": n} for n in names.split(", ") if n]


def open_app(name: str) -> bool:
    return subprocess.run(["open", "-a", name], capture_output=True).returncode == 0


def minimize_all(except_app: str | None, own_title: str) -> tuple[list[str], int]:
    hidden = []
    for w in windows():
        name = w["process"]
        if name == except_app or own_title in name:
            continue
        try:
            _osa(f'tell application "System Events" to set visible of process "{name}" to false')
            hidden.append(name)
        except OSError:
            pass
    return hidden, 0


def restore(names: list[str]) -> int:
    for n in names:
        try:
            _osa(f'tell application "System Events" to set visible of process "{n}" to true')
        except OSError:
            pass
    return len(names)


def close_app(name: str) -> bool:
    try:
        _osa(f'tell application "{name}" to quit')
        return True
    except OSError:
        return False
