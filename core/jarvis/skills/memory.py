"""
============================================================
 Навык «Память»: долговременные факты о пользователе.
   «запомни, что …»          — явная запись
   «что ты обо мне знаешь»   — перечислить
   «забудь …»                — удалить подходящие факты
 После ответов LLM факты извлекаются из реплик пользователя
 в фоне (локальной моделью) — только если в реплике есть
 «я / мой / у меня …». Всё видно и правится на экране «Память».
 Там же резюмируется старая часть диалога (скользящее окно).
============================================================
"""
from __future__ import annotations

import logging
import re
import time

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..engines import engines
from ..security import Risk
from ..text.ru import lemma, plural
from .base import Ctx, Reply, ToolResult, tool

S = "memory"
log = logging.getLogger("jarvis.memory")

CATEGORIES = ["имя", "семья", "предпочтения", "еда", "работа", "дом", "здоровье", "привычки", "покупки", "общее"]


def _person(fact: str) -> str:
    """«я не ем мясо» → «Пользователь не ест мясо» не делаем: храним как сказано, но от 3-го лица по-простому."""
    f = fact.strip().rstrip(".")
    f = re.sub(r"^(что|чтобы)\s+", "", f)
    return f[:1].upper() + f[1:]


def facts(db, profile_id: int) -> list[dict]:
    return [dict(r) for r in db.q("SELECT id, fact, category, source, updated_at FROM memory "
                                  "WHERE profile_id=? ORDER BY updated_at DESC", (profile_id,))]


def _similar(db, profile_id: int, fact: str, cutoff: int = 82) -> dict | None:
    best, score = None, 0
    for f in facts(db, profile_id):
        s = fuzz.token_set_ratio(f["fact"].lower(), fact.lower())
        if s > score:
            best, score = f, s
    return best if score >= cutoff else None


def upsert(db, profile_id: int, fact: str, category: str = "общее", source: str = "user") -> int:
    fact = _person(fact)
    now = time.time()
    if dup := _similar(db, profile_id, fact):
        db.run("UPDATE memory SET fact=?, category=?, updated_at=? WHERE id=?", (fact, category, now, dup["id"]))
        return dup["id"]
    return db.run("INSERT INTO memory(profile_id, fact, category, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (profile_id, fact, category, source, now, now))


def guess_category(fact: str) -> str:
    f = fact.lower()
    table = [
        ("имя", r"зовут|мое имя|меня называ|обращайся"), ("семья", r"жена|муж|сын|дочь|мама|папа|брат|сестр|дет"),
        ("еда", r"ем\b|не ем|люблю есть|аллерги|вегет|кофе|чай"), ("покупки", r"магазин|заказ|самокат|пятерочк|лавк"),
        ("работа", r"работ|офис|начальник|коллег|проект"), ("дом", r"живу|адрес|квартир|дом\b|город"),
        ("здоровье", r"болит|здоров|врач|таблет"), ("привычки", r"встаю|ложусь|каждый день|по утрам|по вечерам"),
        ("предпочтения", r"люблю|нравится|предпочита|не люблю"),
    ]
    for cat, pat in table:
        if re.search(pat, f):
            return cat
    return "общее"


class RememberArgs(BaseModel):
    fact: str = Field(min_length=2, max_length=500, description="факт о пользователе от первого лица")


@tool("memory.remember", skill=S, title="Запомнить", risk=Risk.LOCAL, args=RememberArgs,
      description="запомнить устойчивый факт о пользователе", summary=lambda a: f"Запомнил: «{a.fact[:60]}»")
def t_remember(ctx: Ctx, a: RememberArgs) -> ToolResult:
    upsert(ctx.db, ctx.profile_id, a.fact, guess_category(a.fact))
    if m := re.search(r"(?:мой|мой любимый) магазин\s*[—-]?\s*(.+)", a.fact.lower()):
        from .order import match_shop
        if shop := match_shop(m.group(1)):
            ctx.session.settings.set("default_shop", shop.id)
    return ToolResult(say="Запомнил, сэр.")


class ForgetArgs(BaseModel):
    query: str = Field(min_length=2)


@tool("memory.forget", skill=S, title="Забыть", risk=Risk.LOCAL, args=ForgetArgs,
      description="удалить факты о пользователе по теме", summary=lambda a: f"Забыл факты про «{a.query}»")
def t_forget(ctx: Ctx, a: ForgetArgs) -> ToolResult:
    q_lemmas = {lemma(w) for w in re.findall(r"[а-яa-z0-9]+", a.query.lower()) if len(w) > 2}
    gone = []
    for f in facts(ctx.db, ctx.profile_id):
        f_lemmas = {lemma(w) for w in re.findall(r"[а-яa-z0-9]+", f["fact"].lower())}
        if q_lemmas and (q_lemmas & f_lemmas or fuzz.partial_ratio(a.query.lower(), f["fact"].lower()) > 85):
            ctx.db.run("DELETE FROM memory WHERE id=?", (f["id"],))
            gone.append(f["fact"])
    if not gone:
        return ToolResult(say="Ничего такого я не помню, сэр.")
    n = len(gone)
    return ToolResult(say=f"Забыл {n} {plural(n, 'факт', 'факта', 'фактов')}, сэр.", log="Забыл:\n• " + "\n• ".join(gone))


@tool("memory.list", skill=S, title="Что я знаю о вас", risk=Risk.READ, description="перечислить факты о пользователе")
def t_list(ctx: Ctx) -> ToolResult:
    fs = facts(ctx.db, ctx.profile_id)
    if not fs:
        return ToolResult(say="Пока ничего, сэр. Скажите «запомни, что …».")
    n = len(fs)
    spoken = "; ".join(f["fact"] for f in fs[:6])
    tail = f" И ещё {n - 6} — на экране «Память»." if n > 6 else ""
    return ToolResult(say=f"Я помню {n} {plural(n, 'факт', 'факта', 'фактов')}: {spoken}.{tail}",
                      log="Память:\n• " + "\n• ".join(f"{f['fact']} ({f['category']})" for f in fs))


# ---------- интенты ----------

async def remember(ctx: Ctx, m, text):
    return (await ctx.call("memory.remember", {"fact": m.group(2)})).say


async def forget(ctx: Ctx, m, text):
    q = re.sub(r"^(про|о|об|что)\s+", "", m.group(2)).strip()
    r = await ctx.call("memory.forget", {"query": q})
    return Reply(say=r.say, log=r.log)


async def what_you_know(ctx: Ctx, m, text):
    r = await ctx.call("memory.list")
    return Reply(say=r.say, log=r.log)


async def set_default_shop(ctx: Ctx, m, text):
    from .order import match_shop
    shop = match_shop(m.group(2))
    if not shop:
        return "Такого магазина нет в каталоге, сэр."
    ctx.session.settings.set("default_shop", shop.id)
    upsert(ctx.db, ctx.profile_id, f"Мой магазин по умолчанию — {shop.title}", "покупки")
    return f"Запомнил: ваш магазин — {shop.title}."


# ---------- фоновая работа после ответа LLM ----------

FIRST_PERSON = re.compile(r"\b(я|мой|моя|мое|мои|меня|мне|у меня|мною|люблю|живу|работаю)\b")

EXTRACT_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
                  "required": ["facts"]}

EXTRACT_PROMPT = (
    "Извлеки из реплики пользователя устойчивые факты о нём самом: имя, семья, предпочтения, "
    "привычки, работа, город, любимые магазины, ограничения в еде. Не включай сиюминутные просьбы, "
    "вопросы и факты о мире. Пиши кратко от первого лица, например «Я не ем мясо». "
    "Если фактов нет — пустой список. Ответ — JSON {\"facts\": [...]}."
)


async def after_turn(session, user_text: str) -> None:
    try:
        if FIRST_PERSON.search(user_text) and engines.llm_ok:
            from ..llm.dialog import plain_json
            out = await plain_json(engines.ollama, session.settings.get("llm_model"), EXTRACT_PROMPT,
                                   user_text, EXTRACT_SCHEMA)
            for f in (out or {}).get("facts", [])[:3]:
                if isinstance(f, str) and 4 < len(f) < 300:
                    upsert(session.db, session.profile_id, f, guess_category(f), source="extracted")
                    await session.emit({"type": "memory"})
        await summarize_if_needed(session)
    except Exception as e:  # noqa: BLE001 — фоновая работа не должна мешать диалогу
        log.warning("память после хода: %s", e)


async def summarize_if_needed(session) -> None:
    window = int(session.settings.get("llm_ctx_turns", 8)) * 2
    db, pid = session.db, session.profile_id
    summ = db.one("SELECT text, upto_id FROM summaries WHERE profile_id=?", (pid,))
    upto = summ["upto_id"] if summ else 0
    rows = db.q("SELECT id, role, text FROM messages WHERE profile_id=? AND id>? ORDER BY id", (pid, upto))
    if len(rows) <= window + 8:
        return
    old = rows[: len(rows) - window]
    convo = "\n".join(f"{'Пользователь' if r['role'] == 'user' else 'Джарвис'}: {r['text']}" for r in old)
    from ..llm.dialog import plain
    prev = summ["text"] if summ else ""
    text = await plain(engines.ollama, session.settings.get("llm_model"),
                       "Сожми разговор в 3–5 коротких предложений: о чём шла речь, что решили, что важно помнить. "
                       "Только факты из текста.",
                       (f"Прежнее резюме: {prev}\n\n" if prev else "") + convo)
    db.run("INSERT INTO summaries(profile_id, text, upto_id) VALUES (?,?,?) "
           "ON CONFLICT(profile_id) DO UPDATE SET text=excluded.text, upto_id=excluded.upto_id",
           (pid, text.strip()[:1500], old[-1]["id"]))
