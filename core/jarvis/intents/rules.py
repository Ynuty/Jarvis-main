"""
============================================================
 INTENTS — быстрые команды без LLM. Порядок важен: побеждает
 первое совпадение. Узкие команды — выше широких (open, search,
 timer, note-add). Новая команда = одна строка intent(...)
 + обработчик в навыке + строка в HELP_LINES (skills/system.py).
 Текст на входе уже нормализован norm(): нижний регистр, ё → е.
============================================================
"""
from __future__ import annotations

import re

from ..skills import day, desktop, info, mail, memory, notes, order, system, timers
from ..skills import knowledge
from .router import intent

INTENTS = [
    # ---------- управление ----------
    intent("silence", r"^(замолчи|молчи|тихо|хватит|стоп|отставить|прекрати|тише уже)$", system.silence),
    intent("sleep", r"(^|\s)(спи|усни|отбой|спокойной ночи|режим ожидания|отдыхай)(\s|$)", system.sleep),
    intent("wake", r"(проснись|подъем|я вернулся|работаем)", system.wake),
    intent("shutdown", r"(выключись|отключи систему|завершить работу|отключение системы|выключение системы)",
           system.shutdown),
    intent("help", r"(что ты умеешь|твои возможности|какие команды|список команд|помоги|помощь|инструкци)",
           system.help_reply),
    intent("status", r"(статус|диагностик|доклад|отчет по системам|как систем|все ли в порядке)", system.status_reply),

    # ---------- время ----------
    intent("time", r"(который час|сколько (сейчас )?времени|текущее время|скажи время|время сейчас)", info.now_time),
    intent("date", r"(какое (сегодня )?число|какая (сегодня )?дата|какой (сегодня )?день(?! рождени)|день недели|"
                   r"число сегодня|сегодня какое)", info.now_date),

    # ---------- таймеры ----------
    intent("timers-cancel", r"(отмени|сбрось|убери|удали|останови).*(таймер|напоминан|будильник)",
           lambda c, m, t: _say(c, "timer.cancel_all")),
    intent("timers-list", r"(какие|сколько|покажи|остал).*(таймер|напоминан)",
           lambda c, m, t: _say(c, "timer.list")),
    intent("reminder", r"напомни(\s+мне)?\s+через\s+(.+)", timers.reminder),
    intent("timer", r"(поставь|заведи|включи|засеки|запусти)?\s*(таймер|будильник|секундомер)?\s*(на)?\s*(.+)?",
           timers.timer, guard=lambda t: bool(re.search(r"(таймер|засеки|будильник)", t))),

    # ---------- день ----------
    intent("day-sheet", r"(открой|покажи)\s+(шторку|день|план дня)$", day.open_sheet),
    intent("day-summary", r"(итог дня|подведи итог|итоги дня|что я сделал сегодня|что ты сделал сегодня)", day.summary),
    intent("day-move", r"(перенеси|перенести)\s+(несделанн\w*|оставш\w*|невыполненн\w*).*(завтра)", day.move_tomorrow),
    intent("day-plan", r"(что у меня (сегодня|на сегодня|по плану)|план на (сегодня|день)|мои задачи|какие (у меня )?задачи)",
           day.plan),
    intent("task-add", r"(добавь задачу|новая задача|запланируй|поставь задачу|добавь в план)\s*:?\s*(.+)", day.add),
    intent("task-done", r"(отметь|отметить|задача)\s+(.+?)\s*(как\s+)?(выполненн\w*|сделанн\w*|готов\w*)$", day.done),
    intent("task-done2", r"(я сделал|я выполнил|сделал задачу|выполнил задачу)\s+(.+)", day.done),
    intent("task-remove", r"(убери|удали|вычеркни)\s+задачу\s+(.+)", day.remove),

    # ---------- память ----------
    intent("memory-list", r"(что ты (обо мне|про меня) знаешь|что ты помнишь обо мне|что ты запомнил)", memory.what_you_know),
    intent("default-shop", r"(мой|основной|любимый) магазин( по умолчанию)?\s*(—|-|это|:)?\s*(.+)",
           lambda c, m, t: memory.set_default_shop(c, _Group2(m.group(4)), t)),
    intent("memory-forget", r"^(забудь|удали из памяти|не помни)\s+(?!заметк)(.+)", memory.forget,
           guard=lambda t: "заметк" not in t),
    intent("memory-remember", r"^(запомни|запомни что|запомни,)\s*,?\s*(?:что\s+)?(.+)", memory.remember),

    # ---------- заказ ----------
    intent("order-cart", r"(что (сейчас |у меня )?в корзине|покажи корзину|прочитай корзину|состав заказа)", order.cart),
    intent("order-repeat", r"(повтори (прошлый|последний) заказ|закажи как в прошлый раз|то же что в прошлый раз)",
           order.repeat_last),
    intent("order-cancel", r"(отмени заказ|очисти корзину|отмени корзину)", order.cancel),
    intent("order", r"\b(закажи|заказать|оформи заказ|закажем|доставь)\b", order.start),

    # ---------- почта ----------
    intent("mail-undo", r"(отмени|верни) (последнюю )?сортировку", mail.undo),
    intent("mail-sort", r"(разбери|рассортируй|отсортируй|разложи|наведи порядок в) (почт\w*|входящи\w*|письма)", mail.sort),
    intent("mail-summary", r"(что (нового|важного) (в почте|во входящих|в письмах)|сводка (по )?почт\w*|проверь почту|"
                           r"есть (ли )?(новые )?письма|сколько (новых )?писем)", mail.summary),
    intent("mail-read", r"(прочитай|прочти|зачитай|перескажи) (письм\w*|последнее письмо|почту)(.*)", mail.read),
    intent("mail-move", r"(перенеси|перемести|переложи) (все )?(рассылки|счета|покупки|соцсети|спам|письма от .+?) (в|во) (.+)",
           mail.move_category),
    intent("mail-rule", r"письма от (.+?) (клади |складывай |перекладывай |отправляй )?(в|во) (.+)", mail.add_rule),
    intent("mail-delete", r"(удали|очисти) (спам|рассылки|письма от .+)", mail.delete_category),
    intent("mail-unsub", r"(отпишись|отписаться) (от )?(.+)", mail.unsubscribe),

    # ---------- справка и сеть ----------
    intent("weather", r"(погод|температур\w* (за окном|на улице)|на улице (холодно|тепло|жарко))", info.weather,
           guard=lambda t: not re.match(r"(найди|поищи|загугли|погугли)\b", t)),
    intent("knowledge", r"(в моих (заметках|документах|файлах)|по моим документам|в базе знаний)\s*(.*)", knowledge.ask),
    intent("wiki", r"(что такое|кто такой|кто такая|кто такие|расскажи (?:про|о|об)|что за)\s+(.+)", info.wiki,
           guard=lambda t: not re.search(r"(себе|себя|тебя|меня|мне)\b", t)),
    intent("search", r"(найди|поищи|загугли|погугли|поиск|ищи)\s+(.+)", info.search,
           guard=lambda t: not re.search(r"(письм|в почте|задач)", t)),

    # ---------- рабочий стол ----------
    intent("apps-refresh", r"(обнови|перечитай) (список )?(программ|приложений)", desktop.refresh_apps),
    intent("minimize-all", r"(сверни|скрой) (все|всё)( окна)?$|покажи рабочий стол", desktop.minimize_all),
    intent("windows", r"(какие|что) (окна|программы) (открыты|запущены)", desktop.windows),
    intent("media", r"(поставь на паузу|пауза|продолжи|следующий трек|следующая песня|предыдущий трек|"
                    r"включи музыку дальше|выключи звук|без звука)", desktop.media),
    intent("sys-volume", r"(громкость системы|системную громкость|звук компьютера|сделай звук)\s*(громче|тише|прибавь|убавь)?",
           desktop.sys_volume),
    intent("folder", r"(открой|покажи)\s+(папку\s+)?(загрузки|документы|рабочий стол|изображения|картинки|музыку|видео)$",
           lambda c, m, t: desktop.folder(c, _Group2(m.group(3)), t)),
    intent("open", r"(открой|запусти|включи|покажи)\s+(.+)", desktop.open_site,
           # установленная программа важнее сайта: «запусти спотифай» откроет приложение, если оно есть
           guard=lambda t: desktop.site_for(t) is not None and not re.search(r"(программ|приложени)", t)
           and not desktop.app_guard(t)),
    intent("focus", r"(переключись на|перейди в|покажи окно|разверни окно)\s+(.+)", desktop.focus),
    intent("close", r"(закрой|закрыть)\s+(окно\s+|программу\s+)?(.+)",
           lambda c, m, t: desktop.close(c, _Group2(m.group(3)), t)),

    # ---------- заметки ----------
    intent("note-add", r"(запиши|заметка|добавь в заметки|отметь)\s*:?\s*(.+)", notes.add),
    intent("note-read", r"(что я записал|мои заметки|прочитай заметки|прочти заметки|список заметок|покажи заметки)",
           notes.read),
    intent("note-clear", r"(удали|очисти|сотри|забудь).*(заметк)", notes.clear),
    intent("open-app", r"(открой|запусти|включи)\s+(.+)", desktop.open_app, guard=desktop.app_guard),

    # ---------- счёт ----------
    intent("percent", r"(\d+(?:[.,]\d+)?)\s*процент\w*\s+от\s+(\d+(?:[.,]\d+)?)", info.percent, nums=True),
    intent("sqrt", r"корень из\s+(\d+(?:[.,]\d+)?)", info.sqrt, nums=True),
    intent("math", r"(посчитай|вычисли|сколько будет|реши|сколько это)|(\d\s*[-+*/^]\s*\d)|"
                   r"(\d+\s+(плюс|минус|умножить|разделить|делить))", info.math, nums=True),

    # ---------- случай ----------
    intent("coin", r"(монетк|орел или решк|подбрось)", info.coin),
    intent("dice", r"(кубик|брось кость|игральн)", info.dice),
    intent("random", r"(случайное число|рандом|загадай число)(.*)", info.rnd),
    intent("choose", r"(выбери|что выбрать|подскажи вариант)(?:\s+из)?\s*:?\s*(.+)", info.choose),

    # ---------- голос и интерфейс ----------
    intent("volume", r"(громче|погромче|тише|потише|громкость)(.*)", system.volume),
    intent("repeat", r"(повтори|что ты сказал|еще раз)", system.repeat),
    intent("mode-open", r"(слушай постоянно|отзывайся всегда|режим без обращения|без обращения|постоянный режим)",
           lambda c, m, t: system.set_mode(c, "open")),
    intent("mode-wake", r"(только по обращению|по имени|режим по обращению|жди обращения)",
           lambda c, m, t: system.set_mode(c, "wake")),
    intent("mode-ptt", r"(только по кнопке|по кнопке|режим кнопки)", lambda c, m, t: system.set_mode(c, "ptt")),
    intent("voice", r"(смени голос|другой голос|голос смени)", system.next_voice),
    intent("fullscreen", r"(полный экран|во весь экран|развернись|разверни интерфейс)", system.fullscreen),
    intent("clear-log", r"(очисти|сотри|обнови).*(журнал|экран|диалог|историю)", system.clear_log),
    intent("protocol", r"протокол\s*(.*)", info.protocol),

    # ---------- характер ----------
    intent("who", r"(кто ты|как тебя зовут|представься|ты кто|что ты такое)", info.who),
    intent("greet", r"^(привет|здравствуй\w*|хай|доброе утро|добрый день|добрый вечер|доброй ночи|хеллоу|салют)",
           info.greet, guard=lambda t: len(t.split()) <= 4),
    intent("howareyou", r"(как (ты|дела|жизнь|сам|настроение)|как себя чувствуеш|что нового)", info.howareyou,
           guard=lambda t: len(t.split()) <= 5),
    intent("thanks", r"(спасибо|благодарю|молодец|отлично сработал|хорошая работа)", info.thanks,
           guard=lambda t: len(t.split()) <= 5),
    intent("joke", r"(анекдот|пошути|шутк|рассмеши|расскажи что-нибудь смешн)", info.joke),
    intent("love", r"(ты мне нравишься|люблю тебя|ты лучший)", info.love),
]


class _Group2:
    """Подсовывает обработчику m.group(2) из другой группы шаблона."""

    def __init__(self, value: str) -> None:
        self.value = value

    def group(self, i: int = 0) -> str:
        return self.value


async def _say(ctx, name: str) -> str:
    return (await ctx.call(name)).say
