"""
============================================================
 Навык «Рабочий стол» (Windows): сайты, программы, окна, папки,
 медиаклавиши, нажатие кнопок по имени.

 Порядок надёжности (из разбора): API приложения / URL → UI Automation
 по элементам → клавиатурные рецепты. Слепых кликов по координатам
 нет совсем. Закрытие окон и нажатие чужих кнопок — с подтверждением:
 там могут быть несохранённые данные.

 Программы ищутся по ярлыкам меню «Пуск» (свои и общие), fuzzy-матч
 по названию. Вкладки браузера без расширения не видны — новая
 вкладка по URL открывается всегда.
============================================================
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import re
import subprocess
import sys
import time
import webbrowser
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from ..security import Risk
from ..text.ru import lemma
from .base import Ctx, ToolResult, tool

S = "desktop"
WIN = sys.platform == "win32"

SITES = [
    (r"ютуб|youtube|видео", "YouTube", "https://www.youtube.com/"),
    (r"гугл|google|поисковик", "Google", "https://www.google.com/"),
    (r"почт|gmail|мейл", "почту", "https://mail.google.com/"),
    (r"карт|навигат", "карты", "https://yandex.ru/maps/"),
    (r"перевод", "переводчик", "https://translate.google.com/?sl=auto&tl=ru"),
    (r"википед", "Википедию", "https://ru.wikipedia.org/"),
    (r"github|гитхаб", "GitHub", "https://github.com/"),
    (r"яндекс(?! (музык|карт|лавк|еда))", "Яндекс", "https://ya.ru/"),
    (r"музык|spotify|спотифай", "музыку", "https://music.yandex.ru/"),
    (r"новост", "новости", "https://news.google.com/?hl=ru"),
    (r"календар", "календарь", "https://calendar.google.com/"),
]

# Русские названия популярных программ → что искать в ярлыках
APP_ALIASES = {
    "телеграм": "telegram", "телега": "telegram", "хром": "chrome", "гугл хром": "chrome",
    "браузер": "edge", "эдж": "edge", "файрфокс": "firefox", "блокнот": "notepad", "калькулятор": "calculator",
    "ворд": "word", "эксель": "excel", "поверпоинт": "powerpoint", "проводник": "explorer",
    "блендер": "blender", "стим": "steam", "дискорд": "discord", "спотифай": "spotify",
    "вс код": "visual studio code", "вскод": "visual studio code", "код": "visual studio code",
    "обсидиан": "obsidian", "зум": "zoom", "скайп": "skype", "ватсап": "whatsapp", "вотсап": "whatsapp",
    "паинт": "paint", "терминал": "terminal", "фото": "фотографии", "фотки": "фотографии",
    "почту windows": "почта", "камеру": "камера", "часы": "часы", "магазин приложений": "microsoft store", "настройки": "settings", "диспетчер задач": "task manager",
}
BUILTIN_APPS = {"notepad": "notepad.exe", "calculator": "calc.exe", "explorer": "explorer.exe",
                "paint": "mspaint.exe", "task manager": "taskmgr.exe", "settings": "ms-settings:",
                "terminal": "wt.exe"}

FOLDERS = {"загрузки": "Downloads", "документы": "Documents", "рабочий стол": "Desktop",
           "изображения": "Pictures", "картинки": "Pictures", "музыка": "Music", "видео": "Videos"}


def site_for(text: str) -> tuple[str, str] | None:
    for pat, label, url in SITES:
        if re.search(pat, text):
            return label, url
    return None


# ---------- программы ----------

_JUNK = re.compile(r"uninstall|удал|readme|help|справк|documentation|website|license|лиценз|release notes")
_index: dict[str, str] = {}
_index_at = 0.0
_INDEX_TTL = 600.0


def _lnk_dirs() -> list[Path]:
    env = os.environ.get
    return [Path(env("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(env("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path.home() / "Desktop", Path(env("PUBLIC", "C:/Users/Public")) / "Desktop",
            Path.home() / "OneDrive" / "Desktop"]


def _store_apps() -> dict[str, str]:
    """Приложения Microsoft Store (UWP) и всё, что видно в «Пуске»: имя → shell:AppsFolder\\AppID."""
    if not WIN:
        return {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ForEach-Object { $_.Name + \"`t\" + $_.AppID }"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return {}
    apps = {}
    for line in out.stdout.splitlines():
        name, _, appid = line.partition("\t")
        if name and appid and not _JUNK.search(name.lower()):
            apps[name.strip().lower()] = "shell:AppsFolder\\" + appid.strip()
    return apps


def _app_paths() -> dict[str, str]:
    """Реестр App Paths: chrome.exe, excel.exe, … — то, что запускается из «Выполнить»."""
    if not WIN:
        return {}
    import winreg
    apps = {}
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    exe = winreg.EnumKey(k, i)
                    apps.setdefault(Path(exe).stem.lower(), exe)
        except OSError:
            continue
    return apps


def app_index(refresh: bool = False) -> dict[str, str]:
    """
    Все запускаемые программы: имя → что открыть. Источники по убыванию надёжности:
    ярлыки «Пуска» и рабочего стола → приложения Store (UWP) → App Paths реестра.
    Кэш на 10 минут; «обнови список программ» — сразу.
    """
    global _index, _index_at
    if _index and not refresh and time.time() - _index_at < _INDEX_TTL:
        return _index
    apps: dict[str, str] = {}
    for root in _lnk_dirs():
        if root.is_dir():
            for p in root.rglob("*.lnk"):
                name = p.stem.lower()
                if not _JUNK.search(name):
                    apps.setdefault(name, str(p))
            for p in root.glob("*.url") if "Desktop" in str(root) else []:
                apps.setdefault(p.stem.lower(), str(p))
    for name, target in _store_apps().items():
        apps.setdefault(name, target)
    for name, target in _app_paths().items():
        apps.setdefault(name, target)
    _index, _index_at = apps, time.time()
    return apps


def _start_menu() -> dict[str, str]:      # совместимость со старым именем
    return app_index()


def app_names() -> list[str]:
    return sorted(app_index().keys(), key=len)


_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def translit(s: str) -> str:
    """«фотошоп» → «fotoshop»: русское произношение латинских названий для нечёткого поиска."""
    return "".join(_TR.get(ch, ch) for ch in s.lower())


def find_app(query: str) -> tuple[str, str] | None:
    """Любая установленная программа по названию (рус./англ., с ошибками). (название, что запустить) или None."""
    q = query.lower().strip().strip("«»\"")
    q = APP_ALIASES.get(q, q)
    for ru, en in APP_ALIASES.items():
        if re.fullmatch(ru + r"[а-я]?", q):
            q = en
    apps = app_index()
    if q in BUILTIN_APPS and not any(q in n for n in apps):
        return q, BUILTIN_APPS[q]
    if not apps:
        return (q, BUILTIN_APPS[q]) if q in BUILTIN_APPS else None
    names = list(apps.keys())
    cands = [q]
    if re.search(r"[а-я]", q):
        t = translit(q)
        cands += [t, t.replace("f", "ph"), t.replace("ks", "x")]   # «фотошоп» → photoshop, «экскалибур» → excalibur
    best = None
    for c in cands:
        for scorer, cut in ((fuzz.WRatio, 80), (fuzz.token_set_ratio, 85)):
            hit = process.extractOne(c, names, scorer=scorer)
            if hit and hit[1] >= cut and (best is None or hit[1] > best[1]):
                best = hit
    if best:
        return best[0], apps[best[0]]
    if q in BUILTIN_APPS:
        return q, BUILTIN_APPS[q]
    if WIN and re.fullmatch(r"[a-z0-9_.-]+", q):
        import shutil
        exe = shutil.which(q) or shutil.which(q + ".exe")      # программы из PATH
        if exe:
            return q, exe
    return None


def _launch(target: str) -> None:
    if WIN:
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 — путь из меню «Пуск» или белого списка
    else:
        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", target])


# ---------- окна (Win32 через ctypes) ----------

if WIN:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def list_windows() -> list[dict]:
    if not WIN:
        return []
    out: list[dict] = []
    own = os.getpid()

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if title in ("Program Manager", "Параметры", "Settings") or pid.value == own:
            return True
        ex = user32.GetWindowLongW(hwnd, -20)        # GWL_EXSTYLE
        if ex & 0x80:                                 # WS_EX_TOOLWINDOW
            return True
        out.append({"hwnd": int(hwnd), "title": title, "pid": pid.value,
                    "minimized": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def find_window(query: str) -> dict | None:
    ws = [w for w in list_windows() if "J.A.R.V.I.S" not in w["title"] and "Джарвис" not in w["title"]]
    if not ws:
        return None
    q = APP_ALIASES.get(query.lower().strip(), query.lower().strip())
    best = process.extractOne(q, {i: w["title"].lower() for i, w in enumerate(ws)}, scorer=fuzz.partial_ratio)
    return ws[best[2]] if best and best[1] >= 70 else None


def _focus(hwnd: int) -> bool:
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # Windows запрещает перехват фокуса фоновым процессам: «нажимаем» Alt, чтобы разрешили.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    return bool(user32.SetForegroundWindow(hwnd))


def _is_elevated_target(hwnd: int) -> bool:
    """UIPI: в окна с правами администратора обычный процесс ввод не отправит."""
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    h = k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return True
    k32.CloseHandle(h)
    return False


# ---------- инструменты ----------

class UrlArgs(BaseModel):
    url: str = Field(pattern=r"^https?://", description="адрес сайта")
    label: str = ""


@tool("desktop.open_url", skill=S, title="Открыть сайт", risk=Risk.OPEN, args=UrlArgs,
      description="открыть сайт в браузере по умолчанию (новая вкладка)",
      summary=lambda a: f"Открыл {a.label or a.url}")
async def t_open_url(ctx: Ctx, a: UrlArgs) -> ToolResult:
    webbrowser.open_new_tab(a.url)
    return ToolResult(say=f"Открываю {a.label or 'сайт'}, сэр.")


class AppArgs(BaseModel):
    name: str = Field(min_length=1, description="название программы")


@tool("desktop.open_app", skill=S, title="Запустить программу", risk=Risk.OPEN, args=AppArgs,
      description="запустить программу по названию (из меню Пуск)", summary=lambda a: f"Запустил {a.name}")
def t_open_app(ctx: Ctx, a: AppArgs) -> ToolResult:
    hit = find_app(a.name)
    if not hit:
        return ToolResult(say=f"Не нашёл программу «{a.name}», сэр.", ok=False)
    w = find_window(hit[0])
    if w:
        _focus(w["hwnd"])
        return ToolResult(say=f"{hit[0].title()} уже открыт — переключил, сэр.")
    _launch(hit[1])
    return ToolResult(say=f"Запускаю {hit[0]}, сэр.", log=f"Запустил {hit[0]} ({Path(hit[1]).name})")


class WinArgs(BaseModel):
    name: str = Field(min_length=1, description="часть заголовка окна или название программы")


@tool("desktop.focus", skill=S, title="Переключиться на окно", risk=Risk.OPEN, args=WinArgs,
      description="переключиться на окно программы", summary=lambda a: f"Переключил на «{a.name}»")
def t_focus(ctx: Ctx, a: WinArgs) -> ToolResult:
    w = find_window(a.name)
    if not w:
        return ToolResult(say=f"Окна «{a.name}» нет, сэр.", ok=False)
    _focus(w["hwnd"])
    return ToolResult(say="Готово, сэр.", log=f"Переключил на «{w['title']}»")


@tool("desktop.minimize_all", skill=S, title="Свернуть окна", risk=Risk.OPEN,
      args=None, description="свернуть все окна (кроме Джарвиса)")
def t_min_all(ctx: Ctx) -> ToolResult:
    n = 0
    for w in list_windows():
        if not w["minimized"]:
            user32.ShowWindow(w["hwnd"], 6)         # SW_MINIMIZE
            n += 1
    return ToolResult(say="Свернул, сэр." if n else "Сворачивать нечего, сэр.", log=f"Свернул окон: {n}")


class KeepArgs(BaseModel):
    keep: str = Field(min_length=1, description="окно, которое оставить")


@tool("desktop.minimize_others", skill=S, title="Свернуть остальные окна", risk=Risk.OPEN, args=KeepArgs,
      description="свернуть все окна, кроме указанного", summary=lambda a: f"Свернул всё, кроме «{a.keep}»")
def t_min_others(ctx: Ctx, a: KeepArgs) -> ToolResult:
    keep = find_window(a.keep)
    n = 0
    for w in list_windows():
        if keep and w["hwnd"] == keep["hwnd"]:
            continue
        if not w["minimized"]:
            user32.ShowWindow(w["hwnd"], 6)
            n += 1
    if keep:
        _focus(keep["hwnd"])
    return ToolResult(say="Готово, сэр.", log=f"Свернул окон: {n}")


@tool("desktop.maximize", skill=S, title="Развернуть окно", risk=Risk.OPEN, args=WinArgs,
      description="развернуть окно на весь экран", summary=lambda a: f"Развернул «{a.name}»")
def t_max(ctx: Ctx, a: WinArgs) -> ToolResult:
    w = find_window(a.name)
    if not w:
        return ToolResult(say=f"Окна «{a.name}» нет, сэр.", ok=False)
    user32.ShowWindow(w["hwnd"], 3)                 # SW_MAXIMIZE
    _focus(w["hwnd"])
    return ToolResult(say="Развернул, сэр.")


@tool("desktop.close", skill=S, title="Закрыть окно", risk=Risk.EXTERNAL, args=WinArgs,
      description="закрыть окно программы (может потерять несохранённые данные — требует подтверждения)",
      summary=lambda a: f"Закрыть окно «{a.name}»")
def t_close(ctx: Ctx, a: WinArgs) -> ToolResult:
    w = find_window(a.name)
    if not w:
        return ToolResult(say=f"Окна «{a.name}» нет, сэр.", ok=False)
    if _is_elevated_target(w["hwnd"]):
        return ToolResult(say="Это окно запущено с правами администратора, сэр. Закройте его вручную.", ok=False)
    user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)     # WM_CLOSE — программа сама спросит о сохранении
    return ToolResult(say="Закрываю, сэр.", log=f"Закрыл «{w['title']}»")


@tool("desktop.refresh_apps", skill=S, title="Обновить список программ", risk=Risk.READ,
      description="перечитать установленные программы (после установки новой)")
def t_refresh(ctx: Ctx) -> ToolResult:
    n = len(app_index(refresh=True))
    return ToolResult(say=f"Список обновлён: знаю {n} программ, сэр.")


@tool("desktop.windows", skill=S, title="Открытые окна", risk=Risk.READ, description="какие окна открыты")
def t_windows(ctx: Ctx) -> ToolResult:
    ws = list_windows()
    if not ws:
        return ToolResult(say="Открытых окон нет, сэр.")
    titles = [w["title"][:60] for w in ws]
    return ToolResult(say=f"Открыто окон: {len(ws)}. " + "; ".join(titles[:5]) + ".",
                      log="Окна:\n• " + "\n• ".join(titles))


class MediaArgs(BaseModel):
    key: str = Field(pattern=r"^(play|next|prev|mute|volup|voldown)$")


_VK = {"play": 0xB3, "next": 0xB0, "prev": 0xB1, "mute": 0xAD, "volup": 0xAF, "voldown": 0xAE}


@tool("desktop.media", skill=S, title="Медиаклавиша", risk=Risk.OPEN, args=MediaArgs,
      description="медиа: play (пауза/продолжить), next, prev, mute, volup, voldown — громкость системы",
      summary=lambda a: f"Медиаклавиша {a.key}")
def t_media(ctx: Ctx, a: MediaArgs) -> ToolResult:
    vk = _VK[a.key]
    for _ in range(5 if a.key in ("volup", "voldown") else 1):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
    return ToolResult(say="", log=f"Медиаклавиша: {a.key}")


class FolderArgs(BaseModel):
    name: str = Field(description="загрузки, документы, рабочий стол, изображения, музыка, видео")


@tool("desktop.open_folder", skill=S, title="Открыть папку", risk=Risk.OPEN, args=FolderArgs,
      description="открыть стандартную папку пользователя", summary=lambda a: f"Открыл папку «{a.name}»")
def t_folder(ctx: Ctx, a: FolderArgs) -> ToolResult:
    key = next((k for k in FOLDERS if k in a.name.lower()), None)
    if not key:
        return ToolResult(say="Такой папки не знаю, сэр.", ok=False)
    _launch(str(Path.home() / FOLDERS[key]))
    return ToolResult(say=f"Открываю {key}, сэр.")


class ButtonArgs(BaseModel):
    window: str = Field(min_length=1)
    button: str = Field(min_length=1, description="надпись на кнопке")


@tool("desktop.press_button", skill=S, title="Нажать кнопку в окне", risk=Risk.EXTERNAL, args=ButtonArgs,
      description="нажать кнопку по надписи в окне программы (UI Automation, требует подтверждения)",
      summary=lambda a: f"Нажать «{a.button}» в окне «{a.window}»")
def t_press(ctx: Ctx, a: ButtonArgs) -> ToolResult:
    import uiautomation as auto
    w = find_window(a.window)
    if not w:
        return ToolResult(say=f"Окна «{a.window}» нет, сэр.", ok=False)
    ctrl = auto.ControlFromHandle(w["hwnd"])
    btn = ctrl.ButtonControl(searchDepth=12, Name=a.button)
    if not btn.Exists(2, 0.2):
        btn = ctrl.Control(searchDepth=12, SubName=a.button)
        if not btn.Exists(1, 0.2):
            return ToolResult(say=f"Кнопку «{a.button}» не нашёл. Возможно, программа не показывает свои элементы.", ok=False)
    pattern = btn.GetInvokePattern() if hasattr(btn, "GetInvokePattern") else None
    if pattern:
        pattern.Invoke()
    else:
        return ToolResult(say="Эту кнопку нажать нельзя без кликов по координатам, а их я не делаю, сэр.", ok=False)
    time.sleep(0.3)
    return ToolResult(say="Нажал, сэр.", log=f"Нажал «{a.button}» в «{w['title']}»")


# ---------- интенты ----------

async def open_site(ctx: Ctx, m, text):
    hit = site_for(text)
    if not hit:
        return None
    label, url = hit
    return (await ctx.call("desktop.open_url", {"url": url, "label": label})).say


def app_guard(text: str) -> bool:
    m = re.search(r"(открой|запусти|включи)\s+(.+)", text)
    return bool(m and find_app(_strip_app(m.group(2))))


def _strip_app(s: str) -> str:
    s = re.sub(r"^(программу|приложение|мне)\s+", "", s.strip())
    s = re.sub(r"\s+(и|а)\s+.*$", "", s)
    return s


async def open_app(ctx: Ctx, m, text):
    name = _strip_app(m.group(2))
    hit = find_app(name)
    if not hit:
        return None
    r = await ctx.call("desktop.open_app", {"name": name})
    rest = re.search(r"\s(?:и|а)\s+(сверни|скрой)\s+(все\s+)?(остальн\w+|другие)", text)
    if rest and r.ok:
        await asyncio.sleep(1.0)
        await ctx.call("desktop.minimize_others", {"keep": hit[0]})
        return f"Открыл {hit[0]} и свернул остальное, сэр."
    return r.say


async def refresh_apps(ctx: Ctx, m, text):
    return (await ctx.call("desktop.refresh_apps")).say


async def minimize_all(ctx: Ctx, m, text):
    return (await ctx.call("desktop.minimize_all")).say


async def focus(ctx: Ctx, m, text):
    return (await ctx.call("desktop.focus", {"name": m.group(2)})).say


async def close(ctx: Ctx, m, text):
    return (await ctx.call("desktop.close", {"name": m.group(2)})).say


async def media(ctx: Ctx, m, text):
    key = ("next" if re.search(r"следующ|дальше|переключи трек", text) else
           "prev" if re.search(r"предыдущ|назад", text) else
           "mute" if re.search(r"выключи звук|без звука", text) else "play")
    await ctx.call("desktop.media", {"key": key})
    return {"next": "Следующий трек.", "prev": "Предыдущий трек.", "mute": "Звук выключен.", "play": "Готово."}[key]


async def sys_volume(ctx: Ctx, m, text):
    up = bool(re.search(r"громче|прибав|увелич", text))
    await ctx.call("desktop.media", {"key": "volup" if up else "voldown"})
    return "Громкость системы " + ("прибавил." if up else "убавил.")


async def folder(ctx: Ctx, m, text):
    return (await ctx.call("desktop.open_folder", {"name": m.group(2)})).say


async def windows(ctx: Ctx, m, text):
    r = await ctx.call("desktop.windows")
    from .base import Reply
    return Reply(say=r.say, log=r.log)


def lemmas(s: str) -> set[str]:
    return {lemma(w) for w in re.findall(r"[а-я]+", s)}
