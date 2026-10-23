"""Парсер заказа: магазин, позиции, количества, единицы."""
import pytest

from jarvis.skills.order import match_shop, parse_item, parse_order
from jarvis.text.ru import norm


def items(text):
    shop, its = parse_order(norm(text))
    return (shop.id if shop else None), [(i.name, i.qty, i.unit) for i in its]


def test_pyaterochka_classic():
    assert items("закажи из Пятёрочки молоко, хлеб и два десятка яиц") == (
        "pyaterochka", [("молоко", 1, "шт"), ("хлеб", 1, "шт"), ("яйца", 20, "шт")])


def test_samokat():
    assert items("Закажи из Самоката бананы и сыр") == ("samokat", [("бананы", 1, "шт"), ("сыр", 1, "шт")])


def test_dodo_pizza():
    assert items("закажи из Додо пиццу пепперони") == ("dodo", [("пицца пепперони", 1, "шт")])


def test_units_and_numbers():
    shop, its = items("закажи из лавки три литра молока, килограмм яблок, пачку масла и 200 грамм сыра")
    assert shop == "lavka"
    assert its == [("молоко", 3, "л"), ("яблоки", 1, "кг"), ("масло", 1, "уп"), ("сыр", 200, "г")]


def test_no_shop_named():
    assert items("закажи молоко и хлеб") == (None, [("молоко", 1, "шт"), ("хлеб", 1, "шт")])


@pytest.mark.parametrize("text,sid", [
    ("пятерочка", "pyaterochka"), ("перекресток", "perekrestok"), ("вкусвилл", "vkusvill"), ("магнит", "magnit"),
    ("ленту", "lenta"), ("ашан", "auchan"), ("самокат", "samokat"), ("яндекс лавка", "lavka"),
    ("яндекс еда", "eda"), ("купер", "kuper"), ("озон фреш", "ozonfresh"), ("додо", "dodo"),
])
def test_shop_catalog(text, sid):
    assert match_shop(text).id == sid


@pytest.mark.parametrize("chunk,expect", [
    ("десяток яиц", ("яйца", 10, "шт")), ("пару бананов", ("бананы", 2, "шт")),
    ("полкило творога", ("творог", 0.5, "кг")), ("две бутылки воды", ("вода", 2, "бут")),
    ("дюжину яиц", ("яйца", 12, "шт")), ("пять штук лимонов", ("лимоны", 5, "шт")),
])
def test_parse_item(chunk, expect):
    it = parse_item(norm(chunk))
    assert (it.name, it.qty, it.unit) == expect
