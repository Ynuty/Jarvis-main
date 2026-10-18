"""Навык «Рабочий стол»: программы, окна, ссылки."""
from __future__ import annotations

import re
import webbrowser
from urllib.parse import quote_plus

from ...security import Risk
from ..base import Skill, Tool, ToolResult, schema
from . import apps

OWN_TITLE = "Джарвис"
SAFE_NAME = re.compile(r"^[\w .+\-]{1,60}$")


def _backend(ctx):
    if ctx.platform == "win32":
        from . import win
        return win
    if ctx.platform == "darwin":
        from . import mac
        return mac
    return None


def _no_backend() -> ToolResult:
    return ToolResult(False, "Управление окнами пока поддерживается только в Windows и macOS")


def open_app(ctx, app: str) -> ToolResult:
    if not SAFE_NAME.match(app):
        return ToolResult(False, "Не понял название программы")
    info = apps.lookup(app)
    if "url" in info:
        return open_url(ctx, info["url"], _title=info["title"])
    if ctx.dry_run:
        return ToolResult(True, f"Открыл {info['title']}")
    b = _backend(ctx)
    if b is None:
        return _no_backend()
    ok = b.open_app(info.get("win", [app])) if ctx.platform == "win32" else b.open_app(info.get("mac", app))
    if not ok:
        return ToolResult(False, f"Не нашёл программу «{info['title']}» на этом компьютере")
    return ToolResult(True, f"Открыл {info['title']}")


def open_url(ctx, url: str, _title: str | None = None) -> ToolResult:
    shown = _title or re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    if not re.match(r"^[a-z][a-z0-9+.\-]*:", url):
        url = "https://" + url
    if not url.startswith(("https://", "http://", "about:")):
        return ToolResult(False, "Открываю только веб-ссылки")
    if not ctx.dry_run:
        webbrowser.open(url, new=2)
    return ToolResult(True, f"Открыл {shown}")


def web_search(ctx, query: str) -> ToolResult:
    res = open_url(ctx, "https://duckduckgo.com/?q=" + quote_plus(query))
    return ToolResult(res.ok, f"Ищу «{query}»" if res.ok else res.message)


def minimize_all(ctx, except_app: str | None = None) -> ToolResult:
    info = apps.lookup(except_app) if except_app else None
    keep = f", кроме {info['title']}" if info else ""
    if ctx.dry_run:
        return ToolResult(True, f"Свернул окна{keep}", undo={"tool": "desktop.restore_windows",
                                                             "args": {"handles": []}})
    b = _backend(ctx)
    if b is None:
        return _no_backend()
    if ctx.platform == "win32":
        handles, failed = b.minimize_all(info.get("win_process") if info else None, OWN_TITLE)
    else:
        handles, failed = b.minimize_all(info.get("mac") if info else None, OWN_TITLE)
    msg = f"Свернул окна{keep}"
    if failed:
        msg += f". Не удалось свернуть {failed} — возможно, они запущены от администратора"
    return ToolResult(True, msg, undo={"tool": "desktop.restore_windows", "args": {"handles": handles}})


def restore_windows(ctx, handles: list) -> ToolResult:
    if not ctx.dry_run and handles:
        b = _backend(ctx)
        if b:
            b.restore(handles)
    return ToolResult(True, "Вернул свёрнутые окна")


def close_app(ctx, app: str) -> ToolResult:
    if not SAFE_NAME.match(app):
        return ToolResult(False, "Не понял название программы")
    info = apps.lookup(app)
    if ctx.dry_run:
        return ToolResult(True, f"Закрыл {info['title']}")
    b = _backend(ctx)
    if b is None:
        return _no_backend()
    ok = b.close_app(info.get("win_process", f"{app}.exe") if ctx.platform == "win32" else info.get("mac", app))
    return ToolResult(ok, f"Закрыл {info['title']}" if ok else f"{info['title']} не закрылся")


def list_windows(ctx) -> ToolResult:
    if ctx.dry_run:
        return ToolResult(True, "Открытых окон: 0", data=[])
    b = _backend(ctx)
    if b is None:
        return _no_backend()
    items = b.windows()
    titles = ", ".join(w["title"] for w in items[:8])
    return ToolResult(True, f"Открытых окон: {len(items)}. {titles}", data=items)


SKILL = Skill("desktop", "Рабочий стол", [
    Tool("open_app", "Открыть программу по названию",
         schema({"app": {"type": "string", "description": "telegram, chrome, notepad, calculator, explorer, vscode, spotify, word, excel или своё"}}, ["app"]),
         Risk.LOW, open_app, describe=lambda a: f"Открыть {apps.lookup(a['app'])['title']}?"),
    Tool("open_url", "Открыть сайт или ссылку в браузере",
         schema({"url": {"type": "string"}}, ["url"]), Risk.LOW, open_url),
    Tool("web_search", "Найти в интернете через браузер",
         schema({"query": {"type": "string"}}, ["query"]), Risk.LOW, web_search),
    Tool("minimize_all", "Свернуть все окна, при необходимости оставив одну программу",
         schema({"except_app": {"type": "string"}}), Risk.LOW, minimize_all),
    Tool("close_app", "Закрыть программу (несохранённые данные могут пропасть)",
         schema({"app": {"type": "string"}}, ["app"]), Risk.HIGH, close_app,
         describe=lambda a: f"Закрыть {apps.lookup(a['app'])['title']}?"),
    Tool("list_windows", "Показать открытые окна", schema(), Risk.SAFE, list_windows),
    Tool("restore_windows", "Вернуть свёрнутые окна", schema({"handles": {"type": "array"}}, ["handles"]),
         Risk.LOW, restore_windows, hidden=True),
])
