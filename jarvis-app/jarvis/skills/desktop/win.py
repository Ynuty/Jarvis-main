"""Windows: окна через WinAPI (ctypes), без сторонних пакетов.

Приоритет из документа: API приложения → UI Automation → клики по координатам.
Здесь используется уровень API ОС (ShowWindow, ShellExecute). Результат
проверяется после действия: окна с правами администратора (UIPI) не
сворачиваются из обычного процесса — об этом сообщаем пользователю.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

SW_MINIMIZE, SW_RESTORE = 6, 9
GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x00000080
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def windows(include_minimized: bool = False) -> list[dict]:
    """Видимые окна верхнего уровня с заголовком (как на панели задач)."""
    result: list[dict] = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        title = _title(hwnd)
        if not title or title == "Program Manager":
            return True
        minimized = bool(user32.IsIconic(hwnd))
        if minimized and not include_minimized:
            return True
        result.append({"hwnd": int(hwnd), "title": title, "process": _process_name(hwnd),
                       "minimized": minimized})
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result


def open_app(candidates: list[str]) -> bool:
    for c in candidates:
        target = os.path.expandvars(c)
        if ("\\" in target or "/" in target) and not os.path.exists(target):
            continue
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except OSError:
            continue
    return False


def minimize_all(except_process: str | None, own_title: str) -> tuple[list[int], int]:
    """Свернуть окна, кроме указанной программы и окна самого Джарвиса.
    Возвращает (свёрнутые hwnd, сколько не удалось свернуть)."""
    done, failed = [], 0
    for w in windows():
        if own_title in w["title"]:
            continue
        if except_process and w["process"] == except_process:
            continue
        user32.ShowWindow(w["hwnd"], SW_MINIMIZE)
        if user32.IsIconic(w["hwnd"]):
            done.append(w["hwnd"])
        else:
            failed += 1  # вероятно, окно с правами администратора (UIPI)
    return done, failed


def restore(hwnds: list[int]) -> int:
    n = 0
    for h in hwnds:
        if user32.IsWindow(h):
            user32.ShowWindow(h, SW_RESTORE)
            n += 1
    return n


def close_app(process: str) -> bool:
    # Без /F: программа получает WM_CLOSE и может спросить про несохранённое.
    r = subprocess.run(["taskkill", "/IM", process], capture_output=True)
    return r.returncode == 0
