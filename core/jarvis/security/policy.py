"""
============================================================
 Политика безопасности — вертикаль, через которую проходит
 КАЖДОЕ действие навыка, кем бы оно ни было предложено
 (правило, LLM, автоматизация).

 Уровни риска:
   read     — только читает                     → без подтверждения
   local    — меняет локальные данные (заметки)  → без подтверждения, в журнал
   open     — открывает программу / сайт          → без подтверждения, в журнал
   external — меняет данные снаружи (почта)       → подтверждение
   danger   — необратимо: отправить/удалить/купить → подтверждение всегда,
              отключить нельзя (настройки такой нет намеренно)

 Сеть: инструменты с network=True работают, только если в реплике
 пользователя есть явная просьба (explicit_re). LLM не может «сама
 решить» сходить в интернет.

 Недоверенный контекст: если в ход попали чужие данные (письмо,
 страница, документ), любое действие выше read требует подтверждения.
============================================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Risk(str, Enum):
    READ = "read"
    LOCAL = "local"
    OPEN = "open"
    EXTERNAL = "external"
    DANGER = "danger"

    @property
    def rank(self) -> int:
        return ["read", "local", "open", "external", "danger"].index(self.value)


@dataclass
class Decision:
    allow: bool
    confirm: bool = False
    reason: str = ""


# Слова, которыми пользователь прямо просит сходить в сеть.
NETWORK_ASK = re.compile(
    r"(найди|поищи|загугли|погугли|в сети|в интернете|онлайн|поиск|погод|температур|"
    r"что такое|кто так|расскажи (про|о|об)|википед|справк|закажи|заказ|почт|письм|входящ)"
)


class KillSwitch:
    """Аварийная остановка: «стоп» / Esc обрывает всё, что выполняется."""

    def __init__(self) -> None:
        self.generation = 0

    def trip(self) -> int:
        self.generation += 1
        return self.generation

    def alive(self, gen: int) -> bool:
        return gen == self.generation


def check(tool, user_text: str, *, untrusted: bool = False,
          disabled: set[str] | None = None, origin: str = "rule") -> Decision:
    """
    Решение по вызову инструмента.
    origin: rule — сработало регулярное правило по реплике пользователя;
            llm  — инструмент предложила модель;
            auto — внутренний сценарий (таймер, автоматизация).
    """
    if tool is None:
        return Decision(False, reason="Такого действия нет в реестре.")
    if disabled and (tool.name in disabled or tool.skill in disabled):
        return Decision(False, reason="Действие отключено в настройках.")

    if tool.network:
        pattern = re.compile(tool.explicit_re) if tool.explicit_re else NETWORK_ASK
        if not pattern.search(user_text or ""):
            return Decision(False, reason="Сеть — только по явной просьбе.")

    risk: Risk = tool.risk
    need = risk in (Risk.EXTERNAL, Risk.DANGER)
    if untrusted and risk.rank > Risk.READ.rank:
        need = True
    # Модель не может сама поднять «открыть» в «удалить» без согласия:
    # всё, что LLM предлагает выше local, показываем карточкой.
    if origin == "llm" and risk.rank >= Risk.EXTERNAL.rank:
        need = True
    return Decision(True, confirm=need)


YES = re.compile(r"^(да|ага|угу|давай|конечно|подтверждаю|подтвердить|выполняй|выполнять|оформляй|"
                 r"верно|точно|да конечно|да давай|да подтверждаю|поехали|согласен)( .*)?$")
NO = re.compile(r"^(нет|не надо|не нужно|отмена|отмени|отменить|стоп|не|неа|отбой|не выполняй|передумал)( .*)?$")


def is_yes(text: str) -> bool:
    return bool(YES.match(text.strip()))


def is_no(text: str) -> bool:
    return bool(NO.match(text.strip()))
