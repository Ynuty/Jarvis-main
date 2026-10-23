"""
============================================================
 Этап 2 заказов: собрать корзину в ВИДИМОМ окне браузера.
 Playwright + установленный Edge/Chrome, постоянный профиль
 браузера на каждый магазин (вход один раз, сессия хранится
 в %APPDATA%/Jarvis/browser/<магазин>, не в базе Джарвиса).

 Что делает: для каждой позиции открывает поиск, берёт первую
 карточку и нажимает «в корзину» (количество — повторными
 нажатиями для штук). Чего НЕ делает никогда: адрес, оплата,
 кнопка «Оформить». Окно остаётся открытым — дальше человек.
============================================================
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

from pydantic import BaseModel

from .. import config
from ..db import loads
from ..security import Risk
from . import recipes
from .base import Ctx, ToolResult, tool

S = "order"
log = logging.getLogger("jarvis.order_auto")
FORBIDDEN = re.compile(r"(оформ|оплат|pay|checkout|купить сейчас|подтвердить заказ)", re.I)


def has_recipe(shop_id: str) -> bool:
    return shop_id in recipes.available()


async def _browser(p, shop_id: str):
    profile = config.HOME / "browser" / shop_id
    profile.mkdir(parents=True, exist_ok=True)
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            return await p.chromium.launch_persistent_context(
                str(profile), channel=channel, headless=False, locale="ru-RU",
                viewport={"width": 1280, "height": 860}, args=["--disable-blink-features=AutomationControlled"])
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"не удалось открыть браузер: {last}")


async def _add_button(card, rec):
    btn = card.locator(rec.ADD).first
    if await btn.count():
        return btn
    for b in await card.locator("button").all():
        txt = ((await b.inner_text()) or (await b.get_attribute("aria-label")) or "").strip()
        if re.search(rec.ADD_TEXT, txt, re.I) and not FORBIDDEN.search(txt):
            return b
    return None


async def add_items(page, rec, items: list[dict], alive) -> tuple[list[str], list[str]]:
    ok, fail = [], []
    for it in items:
        if not alive():
            break
        await page.goto(rec.SEARCH.format(q=quote(it["name"])), wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(rec.CARD, timeout=12000)
        except Exception:  # noqa: BLE001
            fail.append(it["name"])
            continue
        card = page.locator(rec.CARD).first
        btn = await _add_button(card, rec)
        if btn is None:
            fail.append(it["name"])
            continue
        clicks = int(it["qty"]) if it.get("unit") == "шт" and float(it["qty"]).is_integer() else 1
        for _ in range(max(1, min(clicks, 30))):
            label = ((await btn.inner_text()) or "").strip()
            if FORBIDDEN.search(label):          # страховка: оформление не нажимаем никогда
                break
            await btn.click()
            await asyncio.sleep(0.6)
        ok.append(f"{it['name']} ×{clicks}")
    return ok, fail


class AutoArgs(BaseModel):
    order_id: int


@tool("order.automate", skill=S, title="Собрать корзину в браузере", risk=Risk.EXTERNAL, args=AutoArgs, llm=False,
      description="положить позиции заказа в корзину магазина в видимом окне браузера (без оплаты)",
      summary=lambda a: f"Собрать корзину заказа №{a.order_id} в браузере (оплату не трогаю)")
async def t_automate(ctx: Ctx, a: AutoArgs) -> ToolResult:
    row = ctx.db.one("SELECT * FROM orders WHERE id=? AND profile_id=?", (a.order_id, ctx.profile_id))
    if not row:
        return ToolResult(say="Заказ не найден, сэр.", ok=False)
    rec = recipes.available().get(row["shop"])
    if not rec:
        return ToolResult(say="Для этого магазина нет рецепта автоматизации.", ok=False)
    from playwright.async_api import async_playwright
    gen = ctx.session.kill.generation
    alive = lambda: ctx.session.kill.alive(gen)  # noqa: E731
    p = await async_playwright().start()
    browser = await _browser(p, row["shop"])
    page = browser.pages[0] if browser.pages else await browser.new_page()
    ok, fail = await add_items(page, rec, loads(row["items"], []), alive)
    await page.goto(rec.HOME, wait_until="domcontentloaded")
    ctx.db.run("UPDATE orders SET status='automated' WHERE id=?", (a.order_id,))
    # окно браузера не закрываем: адрес и оплату пользователь подтверждает сам
    ctx.session.extras["browser"] = (p, browser)
    if not ok:
        return ToolResult(say=f"Не получилось положить товары: возможно, нужен вход. {rec.LOGIN_HINT}", ok=False,
                          log=f"Не нашёл: {', '.join(fail)}")
    say = f"Положил в корзину {len(ok)} из {len(ok) + len(fail)}."
    if fail:
        say += " Не нашёл: " + ", ".join(fail) + "."
    say += " Проверьте корзину, адрес и оплату в окне браузера, сэр."
    return ToolResult(say=say, log="В корзине:\n" + "\n".join(ok) + (("\nНе нашёл: " + ", ".join(fail)) if fail else ""))


async def selftest(shop_id: str, query: str = "молоко") -> tuple[bool, str]:
    """Проверка рецепта: находится ли карточка и кнопка «в корзину». Ничего не нажимает."""
    rec = recipes.available().get(shop_id)
    if not rec:
        return False, "рецепта нет"
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await _browser(p, shop_id)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        try:
            await page.goto(rec.SEARCH.format(q=quote(query)), wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(rec.CARD, timeout=15000)
            n = await page.locator(rec.CARD).count()
            btn = await _add_button(page.locator(rec.CARD).first, rec)
            ok = n > 0 and btn is not None
            return ok, f"карточек: {n}, кнопка «в корзину»: {'есть' if btn else 'нет'}"
        except Exception as e:  # noqa: BLE001
            return False, f"сломан: {str(e).splitlines()[0][:160]}"
        finally:
            await browser.close()
