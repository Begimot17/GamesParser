"""Tests for SteamPriceMonitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.monitors.steam_price_monitor import SteamPriceMonitor


def make_monitor():
    storage = MagicMock()
    storage.init_steam_tables = AsyncMock()
    storage.get_steam_appids = AsyncMock(return_value=[])
    storage.upsert_steam_games = AsyncMock()
    storage.get_steam_game = AsyncMock(return_value=None)
    storage.update_steam_notification = AsyncMock()
    storage._get_connection = AsyncMock()

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)

    monitor = SteamPriceMonitor(storage=storage, bot=bot)
    return monitor


# ── _detect_change tests ──────────────────────────────────────────────────────

def _stored(price_uah=None, original_price_uah=None, notified_price_uah=None):
    return {
        "price_uah": price_uah,
        "original_price_uah": original_price_uah,
        "notified_price_uah": notified_price_uah,
    }


def test_became_free():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=0, new_original=49900, new_discount=100)
    assert result == "became_free"


def test_became_free_already_notified():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=49900, notified_price_uah=0)
    result = monitor._detect_change(stored, new_price=0, new_original=49900, new_discount=100)
    assert result is None


def test_big_discount():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90)
    assert result == "big_discount"


def test_big_discount_below_threshold():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=24950, new_original=49900, new_discount=50)
    assert result is None


def test_big_discount_already_notified_same_price():
    monitor = make_monitor()
    stored = _stored(price_uah=4990, original_price_uah=49900, notified_price_uah=4990)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90)
    assert result is None


def test_big_discount_price_dropped_further():
    monitor = make_monitor()
    # Was at 9900 (80% off), now dropped to 4990 (90% off) — price changed → alert
    stored = _stored(price_uah=9900, original_price_uah=49900, notified_price_uah=9900)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90)
    assert result == "big_discount"


def test_always_free_skipped():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=None, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=0, new_original=None, new_discount=0)
    assert result is None


def test_no_price_change():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=49900, new_original=49900, new_discount=0)
    assert result is None


# ── format_price_alert tests ──────────────────────────────────────────────────

def test_became_free_format():
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.steampowered.com/app/123/",
        old_price_uah=4999,
        new_price_uah=0,
        original_price_uah=4999,
        discount_pct=100,
        alert_type="became_free",
        game_info=None,
    )
    assert "безкоштовною" in msg
    assert "$49.99" in msg
    assert "#free" in msg
    assert "#steam" in msg
    assert "Test Game" in msg


def test_big_discount_format():
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.steampowered.com/app/123/",
        old_price_uah=4999,
        new_price_uah=499,
        original_price_uah=4999,
        discount_pct=90,
        alert_type="big_discount",
        game_info=None,
    )
    assert "знижка" in msg.lower()
    assert "90%" in msg
    assert "#знижка" in msg
    assert "#steam" in msg
    assert "Test Game" in msg


def test_game_info_included():
    from src.bot.message_formatter import MessageFormatter
    from src.services.price_service import GameInfo
    formatter = MessageFormatter()
    info = GameInfo(name="Test", genre="Action, RPG", metacritic=88, developer="Dev Co")
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.steampowered.com/app/123/",
        old_price_uah=49900,
        new_price_uah=0,
        original_price_uah=49900,
        discount_pct=100,
        alert_type="became_free",
        game_info=info,
    )
    assert "Action, RPG" in msg
    assert "Metacritic: 88" in msg
    assert "Dev Co" in msg


def test_html_escaped():
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Game & More <Test>",
        url="https://store.steampowered.com/app/123/",
        old_price_uah=49900,
        new_price_uah=0,
        original_price_uah=49900,
        discount_pct=100,
        alert_type="became_free",
        game_info=None,
    )
    assert "&amp;" in msg
    assert "&lt;" in msg
    assert "&gt;" in msg


# ── _process_result tests ─────────────────────────────────────────────────────

def test_process_result_sends_alert():
    monitor = make_monitor()

    stored = {
        "appid": 730,
        "name": "CS:GO",
        "url": "https://store.steampowered.com/app/730/",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": 4999,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)
    monitor.price_service.get_steam_info = AsyncMock(return_value=None)

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(730, "CS:GO", price_data))

    assert result is True
    monitor.storage.update_steam_notification.assert_called_once_with(730, 0)


def test_process_result_no_alert_no_change():
    monitor = make_monitor()

    stored = {
        "appid": 730,
        "name": "CS:GO",
        "url": "https://store.steampowered.com/app/730/",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": None,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)

    price_data = {"price_uah": 4999, "original_price_uah": 4999, "discount_pct": 0}
    result = asyncio.run(monitor._process_result(730, "CS:GO", price_data))

    assert result is False
    monitor.storage.update_steam_notification.assert_not_called()


def test_process_result_no_stored_game():
    monitor = make_monitor()
    monitor.storage.get_steam_game = AsyncMock(return_value=None)

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(730, "Some Game", price_data))

    assert result is False
