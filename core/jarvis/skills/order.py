"""
============================================================
 Навык «Заказ еды и продуктов».

 «закажи из Пятёрочки молоко, хлеб и два десятка яиц»
   → магазин из каталога SHOPS (или магазин по умолчанию),
   → позиции с количеством (words2num + «десяток», «пара», «кило»),
   → названия в именительном падеже (pymorphy3).
 Дальше работает сценарий OrderFlow: Джарвис зачитывает список,
 принимает правки («убери хлеб», «добавь сметану», «молока два»)
 и только после «да» переходит к оформлению.

 Оплату Джарвис не проводит НИКОГДА: адрес и оплату пользователь
 подтверждает в самом сервисе.
 Этап 1: открыть сайт магазина с поиском по каждой позиции.
 Этап 2: собрать корзину в видимом окне браузера (order_auto.py).
============================================================
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import quote

from pydantic import BaseModel, Field

from ..db import dumps, loads
from ..security import Risk, is_no, is_yes
from ..text.ru import NUM, nominative, num, plural, words2num
from .base import Ctx, Reply, ToolResult, tool

S = "order"


@dataclass(frozen=True)
class Shop:
    id: str
    title: str
    pattern: str
    search: str           # шаблон ссылки поиска, {q} — запрос
    kind: str = "grocery"  # grocery | food


SHOPS = [
    Shop("pyaterochka", "Пятёрочка", r"пятерочк|пятерке|пятерка", "https://5ka.ru/search/?text={q}"),
    Shop("perekrestok", "Перекрёсток", r"перекрест", "https://www.perekrestok.ru/cat/search?search={q}"),
    Shop("vkusvill", "ВкусВилл", r"вкусвил|вкус вил", "https://vkusvill.ru/search/?type=products&q={q}"),
    Shop("magnit", "Магнит", r"магнит", "https://magnit.ru/search?term={q}"),
    Shop("lenta", "Лента", r"\bленты\b|\bлента\b|\bленте\b|\bленту\b", "https://lenta.com/search/?searchText={q}"),
    Shop("auchan", "Ашан", r"ашан", "https://www.auchan.ru/search/?q={q}"),
    Shop("samokat", "Самокат", r"самокат", "https://samokat.ru/search?value={q}"),
    Shop("lavka", "Яндекс Лавка", r"лавк", "https://lavka.yandex.ru/search?text={q}"),
    Shop("eda", "Яндекс Еда", r"яндекс ед|яндекс\.ед|\bеды\b|\bеда\b", "https://eda.yandex.ru/search?query={q}", "food"),
    Shop("kuper", "Купер", r"купер|сбермаркет", "https://kuper.ru/multisearch?q={q}"),
    Shop("ozonfresh", "Озон Фреш", r"озон", "https://www.ozon.ru/category/supermarket-25000/?text={q}"),
    Shop("dodo", "Додо Пицца", r"додо", "https://dodopizza.ru/moscow", "food"),
]


def match_shop(text: str) -> Shop | None:
    t = text.lower().replace("ё", "е")
    for s in SHOPS:
        if re.search(s.pattern, t):
            return s
    return None


def shop_by_id(sid: str) -> Shop | None:
    return next((s for s in SHOPS if s.id == sid), None)


# ---------- разбор позиций ----------

UNITS = {
    r"литр\w*|л\b": "л", r"килограмм\w*|кило\b|кг\b": "кг", r"грамм\w*|гр?\b": "г",
    r"пачк\w*|упаковк\w*": "уп", r"бутылк\w*|бутыл\w*": "бут", r"банк\w*": "банка",
    r"штук\w*|шт\b": "шт", r"бутон\w*": "шт", r"бухан\w*|батон\w*": "шт",
}
MULT = {r"десят\w*|десяток": 10, r"дюжин\w*": 12, r"пар[ауы]?\b": 2}


@dataclass
class Item:
    name: str
    qty: float = 1
    unit: str = "шт"

    def say(self) -> str:
        if self.unit == "шт" and self.qty == 1:
            return self.name
        if self.unit == "шт":
            return f"{self.name} {num(self.qty)} {plural(self.qty, 'штука', 'штуки', 'штук')}"
        return f"{self.name} {num(self.qty)} {self.unit}"

    def dict(self) -> dict:
        return {"name": self.name, "qty": self.qty, "unit": self.unit}


def parse_item(chunk: str) -> Item | None:
    s = words2num(chunk.strip())
    s = re.sub(r"^(еще|ещё|и|а также|плюс)\s+", "", s)
    s = re.sub(r"\b(пожалуйста|штучку|немного)\b", "", s).strip()
    if not s:
        return None
    qty: float | None = None
    unit = "шт"
    if m := re.match(r"^(\d+(?:[.,]\d+)?)\s+(.+)$", s):
        qty, s = float(m.group(1).replace(",", ".")), m.group(2)
    elif m := re.match(r"^(полкило|пол литра|пол-литра|поллитра)\s+(.+)$", s):
        qty, unit, s = 0.5, ("кг" if "кило" in m.group(1) else "л"), m.group(2)
    for pat, k in MULT.items():
        if m := re.match(rf"^({pat})\s+(.+)$", s):
            qty, s = (qty or 1) * k, m.group(m.lastindex)
            break
    for pat, u in UNITS.items():
        if m := re.match(rf"^({pat})\s+(.+)$", s):
            unit, s = u, m.group(m.lastindex)
            if qty is None:
                qty = 1
            break
    name = nominative(s.strip(), plural_form=None)
    if not name or name in NUM:
        return None
    return Item(name=name, qty=qty if qty is not None else 1, unit=unit)


def split_items(text: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+и\s+(?=\S)|\s+а также\s+|\s+плюс\s+", text)
    return [p for p in (x.strip() for x in parts) if p]


def parse_order(text: str) -> tuple[Shop | None, list[Item]]:
    """«закажи из пятерочки молоко, хлеб и два десятка яиц» → (Пятёрочка, [...])"""
    s = re.sub(r"^.*?\b(закажи|заказать|закажем|оформи заказ|купи|доставь)\b\s*", "", text)
    shop = None
    m = re.search(r"\b(?:из|в|с|со)\s+((?:яндекс\s+)?[а-я.]+(?:\s+(?:фреш\w*|пицц[аые]\b|лавк\w*|ед[аыуе]\b))?)", s)
    if m and (shop := match_shop(m.group(1))):
        s = (s[:m.start()] + " " + s[m.end():]).strip()
    elif shop := match_shop(s):
        s = re.sub(shop.pattern + r"\w*", "", s).strip()
    s = re.sub(r"^(мне|нам|домой|продукты|продуктов)\s*:?\s*", "", s).strip(" :,")
    items = [it for it in (parse_item(c) for c in split_items(s)) if it]
    return shop, items


# ---------- корзина ----------

def load_cart(ctx: Ctx) -> tuple[Shop | None, list[Item]]:
    r = ctx.db.one("SELECT shop, items FROM carts WHERE profile_id=?", (ctx.profile_id,))
    if not r:
        return None, []
    return shop_by_id(r["shop"]), [Item(**d) for d in loads(r["items"], [])]


def save_cart(ctx: Ctx, shop: Shop | None, items: list[Item]) -> None:
    if not items:
        ctx.db.run("DELETE FROM carts WHERE profile_id=?", (ctx.profile_id,))
        return
    ctx.db.run("INSERT INTO carts(profile_id, shop, items, updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(profile_id) DO UPDATE SET shop=excluded.shop, items=excluded.items, updated_at=excluded.updated_at",
               (ctx.profile_id, shop.id if shop else "", dumps([i.dict() for i in items]), time.time()))


def cart_text(shop: Shop | None, items: list[Item]) -> str:
    return f"{shop.title if shop else 'Магазин не выбран'}: " + ", ".join(i.say() for i in items)


def _find(items: list[Item], name: str) -> int:
    from rapidfuzz import fuzz, process
    if not items:
        return -1
    target = nominative(words2num(name).strip())
    best = process.extractOne(target, [i.name for i in items], scorer=fuzz.WRatio)
    return best[2] if best and best[1] >= 70 else -1


class OrderFlow:
    """Сценарий правки корзины голосом. Живёт до «да», «отмена» или 5 минут тишины."""
    name = "order"
    ttl = 300.0

    def __init__(self) -> None:
        self.started = time.time()

    @property
    def expired(self) -> bool:
        return time.time() - self.started > self.ttl

    async def handle(self, ctx: Ctx, text: str):
        self.started = time.time()
        shop, items = load_cart(ctx)
        if is_yes(text):
            if not shop:
                return "Из какого магазина заказать, сэр?"
            ctx.session.flow = None
            r = await ctx.call("order.checkout", {}, origin="auto")
            return Reply(say=r.say, log=r.log)
        if is_no(text) or re.search(r"отмени (заказ|корзину)", text):
            ctx.session.flow = None
            save_cart(ctx, shop, [])
            return "Заказ отменён, сэр."

        if not shop and (s := match_shop(text)) and len(text.split()) <= 4:
            save_cart(ctx, s, items)
            return f"{cart_text(s, items)}. Оформлять?"

        if m := re.match(r"^(убери|удали|вычеркни|без|не надо|не нужно)\s+(.+)$", text):
            idx = _find(items, m.group(2))
            if idx < 0:
                return f"В списке нет «{m.group(2)}», сэр."
            gone = items.pop(idx)
            save_cart(ctx, shop, items)
            if not items:
                ctx.session.flow = None
                return f"Убрал {gone.name}. Корзина пуста — заказ отменён."
            return f"Убрал {gone.name}. {cart_text(shop, items)}. Оформлять?"

        if m := re.match(r"^(замени|поменяй)\s+(.+?)\s+на\s+(.+)$", text):
            idx = _find(items, m.group(2))
            new = parse_item(m.group(3))
            if idx < 0 or not new:
                return "Не понял замену, сэр."
            items[idx] = new
            save_cart(ctx, shop, items)
            return f"Заменил. {cart_text(shop, items)}. Оформлять?"

        if m := re.match(r"^(добавь|ещ[её]|плюс|и еще)\s+(.+)$", text):
            new = [it for it in (parse_item(c) for c in split_items(m.group(2))) if it]
            if not new:
                return "Что добавить, сэр?"
            for it in new:
                idx = _find(items, it.name)
                if idx >= 0 and items[idx].unit == it.unit:
                    items[idx].qty += it.qty
                else:
                    items.append(it)
            save_cart(ctx, shop, items)
            return f"Добавил. {cart_text(shop, items)}. Оформлять?"

        # «молока два», «два молока», «яиц тридцать», «хлеба две штуки»
        t = words2num(text)
        if (m := re.match(r"^([а-я ]+?)\s+(\d+(?:[.,]\d+)?)(?:\s+(\S+))?$", t)) or \
           (m2 := re.match(r"^(\d+(?:[.,]\d+)?)\s+([а-я ]+)$", t)):
            name, qty = (m.group(1), m.group(2)) if m else (m2.group(2), m2.group(1))
            idx = _find(items, name)
            if idx >= 0:
                items[idx].qty = float(qty.replace(",", "."))
                save_cart(ctx, shop, items)
                return f"Исправил: {items[idx].say()}. Оформлять?"

        if re.search(r"(что в корзине|прочитай|повтори список|зачитай)", text):
            return f"{cart_text(shop, items)}. Оформлять?"
        return None          # не про корзину — пусть разбирают правила и LLM


# ---------- инструменты ----------

class CartArgs(BaseModel):
    shop: str = Field("", description="магазин из каталога: Пятёрочка, Самокат, ВкусВилл, Лавка и т. п.")
    items: list[str] = Field(default_factory=list, description="позиции с количеством словами: «два десятка яиц»")
    parsed: list[dict] = Field(default_factory=list, description="служебное: уже разобранные позиции")


@tool("order.start", skill=S, title="Собрать корзину", risk=Risk.LOCAL, args=CartArgs,
      description="начать заказ продуктов или еды: магазин и список позиций (оплату не проводит)",
      summary=lambda a: f"Корзина: {a.shop or 'магазин по умолчанию'}, {len(a.items) or len(a.parsed)} поз.")
def t_start(ctx: Ctx, a: CartArgs) -> ToolResult:
    shop = match_shop(a.shop) if a.shop else shop_by_id(ctx.setting("default_shop", ""))
    items = [Item(**d) for d in a.parsed] or [it for it in (parse_item(x) for x in a.items) if it]
    return _begin(ctx, shop, items)


def _begin(ctx: Ctx, shop: Shop | None, items: list[Item]) -> ToolResult:
    if not items:
        return ToolResult(say="Что заказать, сэр?", ok=False)
    save_cart(ctx, shop, items)
    ctx.session.flow = OrderFlow()
    if not shop:
        return ToolResult(say="Из какого магазина заказать, сэр? Можно сказать «мой магазин — Самокат», запомню.")
    return ToolResult(say=f"{cart_text(shop, items)}. Оформлять?", data={"cart": [i.dict() for i in items], "shop": shop.id})


class CheckoutArgs(BaseModel):
    mode: str = Field("", description="служебное: links | auto")


@tool("order.checkout", skill=S, title="Перейти к оформлению заказа", risk=Risk.OPEN, args=CheckoutArgs,
      description="открыть сайт магазина с поиском позиций из корзины", llm=False,
      summary=lambda a: "Открыл магазин с позициями корзины")
async def t_checkout(ctx: Ctx, a: CheckoutArgs) -> ToolResult:
    shop, items = load_cart(ctx)
    if not shop or not items:
        return ToolResult(say="Корзина пуста, сэр.", ok=False)
    mode = a.mode or ("auto" if ctx.setting("order_automation") else "links")
    oid = ctx.db.run("INSERT INTO orders(profile_id, shop, items, ts, status) VALUES (?,?,?,?,?)",
                     (ctx.profile_id, shop.id, dumps([i.dict() for i in items]), time.time(), "opened"))
    if mode == "auto":
        from . import order_auto
        if order_auto.has_recipe(shop.id):
            r = await ctx.session.call_tool(ctx, "order.automate", {"order_id": oid}, origin="auto", preconfirmed=True)
            if r.ok:
                return r
    import webbrowser
    opened = 0
    for it in items[:8]:
        if "{q}" in shop.search:
            webbrowser.open_new_tab(shop.search.format(q=quote(it.name)))
            opened += 1
    if not opened:
        webbrowser.open_new_tab(shop.search)
    save_cart(ctx, shop, items)       # корзина остаётся в профиле до «отмени заказ»
    return ToolResult(say=f"Открыл {shop.title} с поиском по {len(items)} "
                          f"{plural(len(items), 'позиции', 'позициям', 'позициям')}. "
                          "Добавьте в корзину и подтвердите адрес и оплату в самом сервисе, сэр.",
                      log=f"Заказ №{oid}: {cart_text(shop, items)}")


@tool("order.cart", skill=S, title="Что в корзине", risk=Risk.READ, description="прочитать текущую корзину")
def t_cart(ctx: Ctx) -> ToolResult:
    shop, items = load_cart(ctx)
    if not items:
        return ToolResult(say="Корзина пуста, сэр.")
    ctx.session.flow = OrderFlow()
    return ToolResult(say=f"{cart_text(shop, items)}. Оформлять?")


@tool("order.repeat_last", skill=S, title="Повторить прошлый заказ", risk=Risk.LOCAL,
      description="положить в корзину позиции прошлого заказа")
def t_repeat(ctx: Ctx) -> ToolResult:
    r = ctx.db.one("SELECT shop, items FROM orders WHERE profile_id=? AND status!='cancelled' ORDER BY id DESC LIMIT 1",
                   (ctx.profile_id,))
    if not r:
        return ToolResult(say="Прошлых заказов нет, сэр.", ok=False)
    return _begin(ctx, shop_by_id(r["shop"]), [Item(**d) for d in loads(r["items"], [])])


@tool("order.cancel", skill=S, title="Отменить заказ", risk=Risk.LOCAL, description="очистить корзину")
def t_cancel(ctx: Ctx) -> ToolResult:
    shop, _ = load_cart(ctx)
    save_cart(ctx, shop, [])
    ctx.session.flow = None
    return ToolResult(say="Заказ отменён, корзина пуста.")


# ---------- интенты ----------

async def start(ctx: Ctx, m, text):
    shop, items = parse_order(text)
    if shop is None:
        shop = shop_by_id(ctx.setting("default_shop", ""))
    if not items:
        if shop:
            save_cart(ctx, shop, [])
            ctx.session.flow = OrderFlow()
        return f"Что заказать{' из ' + shop.title if shop else ''}, сэр?"
    r = await ctx.call("order.start", {"shop": shop.title if shop else "", "parsed": [i.dict() for i in items]})
    return Reply(say=r.say, data=r.data if isinstance(r.data, dict) else None)


async def cart(ctx: Ctx, m, text):
    return (await ctx.call("order.cart")).say


async def repeat_last(ctx: Ctx, m, text):
    return (await ctx.call("order.repeat_last")).say


async def cancel(ctx: Ctx, m, text):
    return (await ctx.call("order.cancel")).say
