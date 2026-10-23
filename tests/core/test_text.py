"""Русские утилиты: числительные, длительности, калькулятор, склонение, падежи."""
import pytest

from jarvis.text.ru import calc, human_duration, nominative, norm, parse_duration, plural, to_expr, words2num


@pytest.mark.parametrize("src,out", [
    ("двадцать пять минут", "25 минут"),
    ("сто двадцать", "120"),
    ("две тысячи триста", "2300"),
    ("тысяча", "1000"),
    ("полтора часа", "1.5 часа"),
    ("от одного до десяти", "от 1 до 10"),
    ("пять и семь", "5 и 7"),
])
def test_words2num(src, out):
    assert words2num(src) == out


@pytest.mark.parametrize("src,sec", [
    ("10 минут", 600), ("пять минут", 300), ("полчаса", 1800), ("полторы минуты", 90),
    ("две с половиной минуты", 150), ("час", 3600), ("1 час 20 минут", 4800), ("90 секунд", 90),
    ("на 7", 420), ("через минуту", 60),
])
def test_parse_duration(src, sec):
    assert parse_duration(src) == sec


def test_human_duration():
    assert human_duration(3725) == "1 час 2 минуты 5 секунд"
    assert human_duration(0) == "0 секунд"
    assert human_duration(120) == "2 минуты"


@pytest.mark.parametrize("n,form", [(1, "яйцо"), (2, "яйца"), (5, "яиц"), (11, "яиц"), (21, "яйцо"), (24, "яйца")])
def test_plural(n, form):
    assert plural(n, "яйцо", "яйца", "яиц") == form


@pytest.mark.parametrize("phrase,value", [
    ("сколько будет 47 умножить на 12", 564), ("2 + 2 * 2", 6), ("(2 + 2) * 2", 8),
    ("сто разделить на восемь", 12.5), ("два в кубе", 8), ("десять минус двадцать", -10),
    ("три в степени четыре", 81),
])
def test_calc(phrase, value):
    assert calc(to_expr(phrase)) == value


def test_calc_no_eval_and_division_by_zero():
    assert calc("__import__('os')") is None
    assert calc(to_expr("пять разделить на ноль")) is None


def test_norm():
    assert norm("Привет, Джарвис! Ёлки?") == "привет, джарвис елки"


@pytest.mark.parametrize("src,out", [
    ("молока", "молоко"), ("яиц", "яйца"), ("бананы", "бананы"), ("пиццу пепперони", "пицца пепперони"),
    ("свежего хлеба", "свежий хлеб"), ("сметану", "сметана"), ("яблок", "яблоки"),
])
def test_nominative(src, out):
    assert nominative(src) == out
