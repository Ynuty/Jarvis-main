"""Быстрый отбор сообщений, похожих на поручение или обещание.

Работает без модели за доли миллисекунды. Нужен, чтобы не гонять через
локальную модель каждое «ок» и мем, и как запасной режим, когда модели нет.
Правила подбирались на типичной рабочей и учебной переписке и будут
дополняться по тестовому набору.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.day.dates import parse_due
from jarvis.models import Message

# Просьбы и поручения (основы глаголов в повелительном и неопределённой формах)
_REQUEST = re.compile(
    r"\b("
    r"сделай|сделайте|подготовь|подготовьте|пришли|пришлите|скинь|скиньте|отправь|отправьте|"
    r"напиши|напишите|проверь|проверьте|посмотри|посмотрите|глянь|гляньте|позвони|позвоните|"
    r"загрузи|загрузите|закинь|закиньте|оформи|оформите|напомни|напомните|купи|купите|"
    r"закажи|закажите|оплати|оплатите|заполни|заполните|сдай|сдайте|подпиши|подпишите|"
    r"согласуй|согласуйте|созвонись|договорись|узнай|узнайте|перешли|перешлите|добавь|добавьте|"
    r"исправь|исправьте|поправь|поправьте|допиши|допишите|выложи|выложите|распечатай|"
    r"забронируй|забронируйте|перенеси|перенесите|ответь|ответьте"
    r")\b"
)
_MODAL = re.compile(
    r"\b(надо|нужно|необходимо|не забудь|не забудьте|не забыть|просьба|прошу|можешь|можете|"
    r"сможешь|сможете|успеешь|успеете|дедлайн|дд|срок)\b"
)
# Обещания самого пользователя: «сделаю», «пришлю», «я за это возьмусь»
_COMMITMENT = re.compile(
    r"\b(сделаю|пришлю|скину|отправлю|напишу|гляну|посмотрю|подготовлю|загружу|закину|"
    r"оформлю|позвоню|проверю|займусь|возьмусь|беру на себя|оплачу|закажу|исправлю|допишу)\b"
)
# Инфинитивы: «надо купить», «не забыть оплатить»
_INFINITIVE = re.compile(
    r"\b(сделать|подготовить|прислать|скинуть|отправить|написать|проверить|посмотреть|позвонить|"
    r"загрузить|оформить|купить|заказать|оплатить|заполнить|сдать|подписать|согласовать|"
    r"записаться|забронировать|перенести|ответить|исправить|доделать|забрать|отнести)\b"
)
_ONLY_REACTION = re.compile(r"^[\W\d_]*(ок|окей|ага|да|спасибо|спс|понял|поняла|супер|класс|ахаха\w*)?[\W\d_]*$")


@dataclass(frozen=True)
class Candidate:
    message: Message
    score: int
    kind: str  # "request" — просят пользователя / "commitment" — пользователь обещал


def is_task_like(text: str) -> bool:
    """Есть ли в тексте просьба, обещание или «надо + действие»."""
    t = text.casefold().replace("ё", "е")
    return bool(_REQUEST.search(t) or _COMMITMENT.search(t) or (_MODAL.search(t) and _INFINITIVE.search(t)))


def score_message(message: Message, self_note: bool = False) -> Candidate | None:
    """self_note — сообщение в «Избранном»: заметка себе, считаем её просьбой к себе."""
    text = message.text.casefold().replace("ё", "е")
    if len(text) < 6 or _ONLY_REACTION.match(text):
        return None

    if message.is_outgoing and not self_note:
        if _COMMITMENT.search(text):
            score = 2 + (1 if parse_due(text, message.date) else 0)
            return Candidate(message, score, "commitment")
        return None

    score = 0
    if _REQUEST.search(text):
        score += 2
    if _MODAL.search(text):
        score += 1
    if _INFINITIVE.search(text):
        score += 1
    if parse_due(text, message.date):
        score += 1
    if score >= 2:
        return Candidate(message, score, "request")
    return None
