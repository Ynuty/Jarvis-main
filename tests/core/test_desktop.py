"""Поиск любой программы: ярлыки, Store, App Paths, русские названия, транслитерация."""
import time

import pytest

from jarvis.intents.router import find
from jarvis.skills import desktop
from jarvis.text.ru import norm

FAKE = {
    "telegram desktop": "shell:AppsFolder\\Telegram!App",
    "adobe photoshop 2024": r"C:\Start\Adobe Photoshop 2024.lnk",
    "visual studio code": r"C:\Start\Visual Studio Code.lnk",
    "obsidian": r"C:\Start\Obsidian.lnk",
    "фотографии": "shell:AppsFolder\\Microsoft.Windows.Photos!App",
    "spotify": "shell:AppsFolder\\Spotify!App",
    "word 2016": r"C:\Start\Word 2016.lnk",
    "chrome": "chrome.exe",
}


@pytest.fixture(autouse=True)
def fake_index(monkeypatch):
    monkeypatch.setattr(desktop, "_index", dict(FAKE))
    monkeypatch.setattr(desktop, "_index_at", time.time())


@pytest.mark.parametrize("query,name", [
    ("телеграм", "telegram desktop"), ("фотошоп", "adobe photoshop 2024"), ("вс код", "visual studio code"),
    ("обсидиан", "obsidian"), ("фото", "фотографии"), ("спотифай", "spotify"), ("ворд", "word 2016"),
    ("хром", "chrome"), ("Photoshop", "adobe photoshop 2024"),
])
def test_find_any_app(query, name):
    assert desktop.find_app(query)[0] == name


def test_unknown_app():
    assert desktop.find_app("несуществующаяпрограмма") is None


@pytest.mark.parametrize("phrase", ["открой фотошоп", "запусти спотифай", "открой обсидиан", "включи телеграм",
                                    "запусти программу ворд"])
def test_open_app_intent(phrase):
    hit = find(norm(phrase))
    assert hit and hit[0].id == "open-app"


def test_refresh_intent():
    assert find(norm("обнови список программ"))[0].id == "apps-refresh"
