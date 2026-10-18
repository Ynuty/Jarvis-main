"""Роутер правил: типовые команды разбираются без LLM — быстро и предсказуемо.

Составные фразы («открой telegram и сверни остальные окна») делятся на шаги.
Если хоть один шаг не узнан, роутер возвращает None и фраза уходит в LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .normalize import canon


@dataclass
class Action:
    skill: str
    tool: str
    args: dict = field(default_factory=dict)
    text: str = ""

    @property
    def name(self) -> str:
        return f"{self.skill}.{self.tool}"


VERBS = {
    "открой", "запусти", "включи", "сверни", "спрячь", "убери", "закрой", "выключи", "заверши",
    "найди", "загугли", "поищи", "погугли", "добавь", "запиши", "создай", "поставь", "запланируй",
    "напомни", "отметь", "вычеркни", "покажи", "расскажи", "что", "какие", "какой", "итог", "итоги",
    "подведи", "отмени", "откати", "стоп", "хватит", "зайди", "перейди", "собери", "сделай", "разверни",
}
SEP = re.compile(r"\s*[,;.]\s+(?:а\s+|и\s+)?(?:потом\s+|затем\s+)?|\s+(?:и потом|и затем|а потом|потом|затем|и)\s+")


def split_steps(text: str) -> list[str]:
    """Делит фразу по «и/потом/запятой», но только перед глаголом-командой:
    «добавь задачу купить хлеб и молоко» остаётся одним шагом."""
    steps: list[str] = []
    last, prev_sep = 0, ""
    pieces: list[tuple[str, str]] = []
    for m in SEP.finditer(text):
        pieces.append((text[last:m.start()], m.group(0)))
        last = m.end()
    pieces.append((text[last:], ""))
    for chunk, sep in pieces:
        first = chunk.split(" ", 1)[0]
        if steps and first not in VERBS:
            steps[-1] = steps[-1] + prev_sep + chunk
        elif chunk:
            steps.append(chunk)
        prev_sep = sep
    # Whisper иногда повторяет фразу: «Открой стим. Открой стим.» — это одна команда.
    result: list[str] = []
    for s in (s.strip(" .") for s in steps):
        if s and (not result or result[-1] != s):
            result.append(s)
    return result


# ---- разбор времени для задач -------------------------------------------
TIME_RE = re.compile(
    r"(?:^|\s)(?:в|на|к)\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*(час(?:а|ов)?|утра|дня|вечера))?(?=\s|$)")
TOMORROW_RE = re.compile(r"(?:^|\s)(?:на\s+)?завтра(?=\s|$)")
TODAY_RE = re.compile(r"(?:^|\s)(?:на\s+)?сегодня(?=\s|$)")


def parse_task(rest: str) -> dict:
    args: dict = {}
    if TOMORROW_RE.search(rest):
        args["day_offset"] = 1
        rest = TOMORROW_RE.sub(" ", rest)
    rest = TODAY_RE.sub(" ", rest)
    m = TIME_RE.search(rest)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) in ("дня", "вечера") and hh < 12:
            hh += 12
        if hh < 24 and mm < 60:
            args["time"] = f"{hh:02d}:{mm:02d}"
            rest = rest[:m.start()] + " " + rest[m.end():]
    rest = re.sub(r"^\s*(?:мне\s+)?(?:что(?:бы)?\s+|о том,? что\s+)?", "", rest)
    args["title"] = re.sub(r"\s+", " ", rest).strip(" ,.")
    return args


# ---- правила ------------------------------------------------------------
Builder = Callable[[re.Match, list[Action]], Action | None]
RULES: list[tuple[re.Pattern, Builder]] = []


def rule(pattern: str):
    def deco(fn: Builder) -> Builder:
        RULES.append((re.compile(pattern), fn))
        return fn
    return deco


@rule(r"^(?:стоп|остановись|хватит|аварийная остановка|стоп все)$")
def _stop(m, prev): return Action("system", "stop")


@rule(r"^(?:продолжай|продолжить|возобнови работу|сними остановку)$")
def _resume(m, prev): return Action("system", "resume")


@rule(r"^(?:отмени|отмена|откати|верни как было)(?: (?:последнее|это))?(?: действие)?$")
def _undo(m, prev): return Action("system", "undo")


@rule(r"^(?:открой|покажи|разверни) (?:день|шторку|план(?: на (?:день|сегодня))?)$")
def _day_show(m, prev): return Action("day", "show")


@rule(r"^(?:итог(?:и)? дня|подведи итог(?:и)?(?: дня)?)$")
def _summary(m, prev): return Action("day", "summary")


@rule(r"^(?:какие|покажи|какие у меня)(?: открыты)? (?:окна|открытые окна)(?: открыты)?$")
def _windows(m, prev): return Action("desktop", "list_windows")


@rule(r"^(?:что|какие|какой|покажи|расскажи)\b.*\b(?:сегодня|план\w*|задач\w*|дел[аоу]?)$")
def _today(m, prev): return Action("day", "list_today")


@rule(r"(?:сводк\w+|что нового|что пишут|непрочитанн\w+)")
def _digest(m, prev): return Action("messages", "digest")


@rule(r"^(?:добавь|запиши|создай|поставь|запланируй|напомни)(?: мне)?"
      r"(?: (?:задачу|дело|напоминание|в план|в задачи|в список дел))? (?P<rest>.+)$")
def _add(m, prev):
    args = parse_task(m.group("rest"))
    return Action("day", "add_task", args) if args["title"] else None


@rule(r"^(?:отметь|вычеркни|закрой задачу|я сделал|сделал|выполнил|готово)(?: задачу)?"
      r"(?: (?P<title>.+?))(?: как (?:выполненн|сделанн)\w+| выполненной| сделанной)?$")
def _complete(m, prev):
    return Action("day", "complete_task", {"title": m.group("title")})


@rule(r"^(?:сверни|спрячь|убери)(?: (?P<which>все остальные|остальные|все|другие|лишние))?"
      r"(?: окна)?(?: кроме (?P<keep>[\w .+\-]+))?$")
def _minimize(m, prev):
    args: dict = {}
    if m.group("keep"):
        args["except_app"] = canon(m.group("keep"))
    elif m.group("which") in ("остальные", "все остальные", "другие", "лишние"):
        opened = next((a for a in reversed(prev) if a.tool == "open_app"), None)
        if opened:
            args["except_app"] = opened.args["app"]
    return Action("desktop", "minimize_all", args)


@rule(r"^(?:найди|загугли|поищи|погугли)(?: в интернете)? (?P<q>.+)$")
def _search(m, prev): return Action("desktop", "web_search", {"query": m.group("q")})


@rule(r"^(?:открой|зайди на|перейди на|запусти)(?: сайт)? (?P<url>[\w\-]+(?:\.[\w\-]+)+(?:/\S*)?)$")
def _url(m, prev): return Action("desktop", "open_url", {"url": m.group("url")})


@rule(r"^(?:открой|запусти|включи)(?: программу| приложение)? (?P<app>[\w+\-]+(?: [\w+\-]+){0,3})$")
def _open(m, prev):
    app = canon(m.group("app"))
    if "." in app and " " not in app:  # «открой ютуб» → сайт
        return Action("desktop", "open_url", {"url": app})
    return Action("desktop", "open_app", {"app": app})


@rule(r"^(?:закрой|выключи|заверши)(?: программу| приложение)? (?P<app>[\w .+\-]+)$")
def _close(m, prev): return Action("desktop", "close_app", {"app": canon(m.group("app"))})


def route_step(step: str, prev: list[Action]) -> Action | None:
    for rx, build in RULES:
        m = rx.search(step)
        if m:
            action = build(m, prev)
            if action:
                action.text = step
                return action
    return None


def route(text: str) -> list[Action] | None:
    plan: list[Action] = []
    for step in split_steps(text):
        action = route_step(step, plan)
        if action is None:
            return None
        plan.append(action)
    return plan or None
