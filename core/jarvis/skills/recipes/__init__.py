"""
============================================================
 Рецепты магазинов для автоматизации корзины (этап 2 заказов).
 Один файл — один магазин. Рецепт описывает, как найти товар
 и нажать «В корзину»; оплату и адрес рецепт НЕ трогает никогда.

 Рецепты ломаются при каждом редизайне сайта («вечная поломка
 рецептов» из разбора), поэтому у каждого есть самотест:
   python -m jarvis.skills.recipes selftest samokat
 Он ищет «молоко» и проверяет, что карточка и кнопка находятся.
 Сломанный рецепт → Джарвис откатывается на этап 1 (ссылки поиска).

 Формат рецепта (модуль):
   SHOP_ID, HOME, SEARCH = "https://…{q}", LOGIN_HINT
   CARD   — CSS карточки товара в выдаче
   ADD    — CSS кнопки «в корзину» внутри карточки
   ADD_TEXT — запасной вариант: регулярка по тексту кнопки
   VERIFIED — дата, когда рецепт последний раз проходил самотест
============================================================
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def available() -> dict[str, ModuleType]:
    out = {}
    for m in pkgutil.iter_modules(__path__):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{m.name}")
        if getattr(mod, "SHOP_ID", None):
            out[mod.SHOP_ID] = mod
    return out
