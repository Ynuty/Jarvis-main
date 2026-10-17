"""Командная строка Джарвиса — тестовый режим до появления окна приложения.

Импорт экспорта (тестовый режим):
    jarvis export-chats result.json
    jarvis import result.json --chat "Курсовой проект" --me "Саша"
    jarvis tasks
    jarvis done 3

Живое подключение к аккаунту (только чтение):
    jarvis live setup        # api_id и api_hash с https://my.telegram.org
    jarvis live login
    jarvis live chats
    jarvis live sync --chat "Курсовой проект"
    jarvis live logout
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime

from jarvis.day.extractor import Identity, TaskExtractor
from jarvis.models import ASSIGNEE_UNCLEAR, STATUS_DISMISSED, STATUS_DONE, STATUS_OPEN, Task
from jarvis.storage.db import Database

_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _fmt_due(task: Task) -> str:
    if not task.due_at:
        return "без срока"
    d = task.due_at
    s = f"{_WD[d.weekday()]} {d:%d.%m}"
    if (d.hour, d.minute) != (23, 59):
        s += f" {d:%H:%M}"
    if task.status == STATUS_OPEN and d < datetime.now():
        s += " — просрочено"
    return s


def _print_tasks(db: Database, tasks: list[Task]) -> None:
    if not tasks:
        print("Задач нет.")
        return
    for t in tasks:
        mark = {STATUS_DONE: "✓", STATUS_DISMISSED: "×"}.get(t.status, "•")
        note = "  (возможно, не вам)" if t.assignee == ASSIGNEE_UNCLEAR else ""
        print(f"{mark} [{t.id}] {t.title}{note}")
        meta = [f"срок: {_fmt_due(t)}", f"чат: {db.chat_title(t.chat_id)}"]
        if t.requested_by:
            meta.insert(1, f"от: {t.requested_by}")
        print("      " + " · ".join(meta))


def _make_extractor(args) -> TaskExtractor:
    names = tuple(n for n in (args.me, *(args.name or [])) if n)
    llm = None
    if args.model:
        from jarvis.llm.ollama import OllamaClient

        llm = OllamaClient(model=args.model, url=args.llm_url)
    return TaskExtractor(llm=llm, me=Identity(names))


def _parse_since(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _run_sync(source, chats, args) -> int:
    from jarvis.core.sync import sync

    db = Database(args.db)
    extractor = _make_extractor(args)
    if extractor.llm is None:
        print("Режим без модели: задачи ищутся правилами. Для точного разбора добавьте --model (нужна Ollama).")
    result = sync(source, chats, extractor, db, since=_parse_since(args.since))
    print(
        f"Чатов: {result.chats}, сообщений прочитано: {result.messages_read}, новых: {result.messages_new}, "
        f"новых задач: {len(result.tasks_new)}"
    )
    if extractor.stats.llm_errors:
        print(f"Ошибок модели: {extractor.stats.llm_errors} (для этих сообщений использованы правила)")
    print()
    _print_tasks(db, result.tasks_new)
    return 0


# ---------- команды: экспорт ----------

def cmd_export_chats(args) -> int:
    from jarvis.sources.telegram_export import TelegramExportSource

    src = TelegramExportSource(args.file, me=args.me)
    for chat in src.list_chats():
        print(f"{chat.id:>16}  {chat.kind:<8} {src.message_count(chat.id):>6} сообщ.  {chat.title}")
    return 0


def cmd_import(args) -> int:
    from jarvis.sources.base import resolve_chats
    from jarvis.sources.telegram_export import TelegramExportSource

    src = TelegramExportSource(args.file, me=args.me)
    chats = resolve_chats(src.list_chats(), args.chat)
    return _run_sync(src, chats, args)


# ---------- команды: список дел и журнал ----------

def cmd_tasks(args) -> int:
    db = Database(args.db)
    _print_tasks(db, db.list_tasks(status=None if args.all else STATUS_OPEN))
    return 0


def _set_status(args, status: str, verb: str) -> int:
    db = Database(args.db)
    task = db.get_task(args.id)
    if task is None:
        print(f"Задачи {args.id} нет.")
        return 1
    db.set_status(args.id, status)
    db.log("task_status", task_id=args.id, status=status, title=task.title)
    print(f"{verb}: {task.title}")
    return 0


def cmd_done(args) -> int:
    return _set_status(args, STATUS_DONE, "Сделано")


def cmd_dismiss(args) -> int:
    return _set_status(args, STATUS_DISMISSED, "Убрано из списка")


def cmd_reopen(args) -> int:
    return _set_status(args, STATUS_OPEN, "Снова в списке")


def cmd_log(args) -> int:
    db = Database(args.db)
    for e in reversed(db.list_events(args.limit)):
        details = {k: v for k, v in e.items() if k not in ("ts", "kind")}
        print(f"{e['ts']}  {e['kind']:<14} {details}")
    return 0


# ---------- команды: живое подключение ----------

def _live_source():
    from jarvis.secrets import KeyringStore
    from jarvis.sources.telegram_live import TelegramLiveSource

    return TelegramLiveSource(KeyringStore())


def cmd_live(args) -> int:
    src = _live_source()
    try:
        if args.live_cmd == "setup":
            print("Получите api_id и api_hash на https://my.telegram.org → API development tools.")
            api_id = int(input("api_id: ").strip())
            api_hash = getpass.getpass("api_hash (не отображается): ").strip()
            src.save_api_credentials(api_id, api_hash)
            print("Сохранено в хранилище учётных данных ОС.")
        elif args.live_cmd == "login":
            phone = args.phone or input("Номер телефона в международном формате: ").strip()
            src.login(
                phone,
                code_callback=lambda: input("Код из Telegram: "),
                password_callback=lambda: getpass.getpass("Пароль двухэтапной проверки: "),
            )
            print("Вход выполнен. Джарвис будет только читать выбранные вами чаты.")
        elif args.live_cmd == "chats":
            for chat in src.list_chats():
                print(f"{chat.id:>16}  {chat.kind:<8} {chat.title}")
        elif args.live_cmd == "sync":
            from jarvis.sources.base import resolve_chats

            chats = resolve_chats(src.list_chats(), args.chat)
            return _run_sync(src, chats, args)
        elif args.live_cmd == "logout":
            src.logout()
            print("Сессия завершена и удалена с компьютера.")
        return 0
    finally:
        src.close()


# ---------- разбор аргументов ----------

def _add_extract_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--chat", action="append", required=True,
                   help="id или точное название чата; можно указать несколько раз")
    p.add_argument("--me", help="как вы подписаны в Telegram (нужно для экспорта одного чата)")
    p.add_argument("--name", action="append", help="другие варианты вашего имени в обращениях")
    p.add_argument("--since", help="брать сообщения начиная с даты, например 2026-10-01")
    p.add_argument("--model", help="локальная модель Ollama, например qwen2.5:7b-instruct")
    p.add_argument("--llm-url", default="http://127.0.0.1:11434", help="адрес Ollama (только localhost)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Список дел из переписки в Telegram")
    parser.add_argument("--db", help="путь к базе (по умолчанию — папка данных пользователя)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export-chats", help="показать чаты в файле экспорта")
    p.add_argument("file")
    p.add_argument("--me")
    p.set_defaults(func=cmd_export_chats)

    p = sub.add_parser("import", help="найти задачи в экспорте Telegram Desktop (JSON)")
    p.add_argument("file")
    _add_extract_args(p)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("tasks", help="список дел")
    p.add_argument("--all", action="store_true", help="включая сделанные и убранные")
    p.set_defaults(func=cmd_tasks)

    for name, func, help_ in (
        ("done", cmd_done, "отметить задачу сделанной"),
        ("dismiss", cmd_dismiss, "убрать задачу из списка"),
        ("reopen", cmd_reopen, "вернуть задачу в список"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("id", type=int)
        p.set_defaults(func=func)

    p = sub.add_parser("log", help="журнал действий ассистента")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_log)

    live = sub.add_parser("live", help="живое подключение к аккаунту (только чтение)")
    live_sub = live.add_subparsers(dest="live_cmd", required=True)
    live_sub.add_parser("setup", help="сохранить api_id и api_hash")
    lp = live_sub.add_parser("login", help="войти в аккаунт")
    lp.add_argument("--phone")
    live_sub.add_parser("chats", help="показать чаты аккаунта")
    sp = live_sub.add_parser("sync", help="найти задачи в выбранных чатах")
    _add_extract_args(sp)
    live_sub.add_parser("logout", help="завершить сессию и удалить её с компьютера")
    live.set_defaults(func=cmd_live)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # кириллица в консоли Windows
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
