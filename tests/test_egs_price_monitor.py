"""Tests for EgsPriceMonitor."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.monitors.egs_price_monitor import EgsPriceMonitor


def make_monitor():
    storage = MagicMock()
    storage.init_egs_tables = AsyncMock()
    storage.upsert_egs_games = AsyncMock()
    storage.get_egs_game = AsyncMock(return_value=None)
    storage.update_egs_notification = AsyncMock()
    storage.find_steam_game_by_name = AsyncMock(return_value=None)

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)

    monitor = EgsPriceMonitor(storage=storage, bot=bot)
    return monitor


# ── _detect_change tests ───────────────────────────────────────────────────────

def _stored(price_uah=None, original_price_uah=None, notified_price_uah=None):
    return {
        "price_uah": price_uah,
        "original_price_uah": original_price_uah,
        "notified_price_uah": notified_price_uah,
    }


def test_became_free():
    monitor = make_monitor()
    stored = _stored(price_uah=4999, original_price_uah=4999, notified_price_uah=4999)
    result = monitor._detect_change(stored, new_price=0, new_original=4999, new_discount=100, discount_threshold=90)
    assert result == "became_free"


def test_became_free_already_notified():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=4999, notified_price_uah=0)
    result = monitor._detect_change(stored, new_price=0, new_original=4999, new_discount=100, discount_threshold=90)
    assert result is None


def test_big_discount():
    monitor = make_monitor()
    stored = _stored(price_uah=4999, original_price_uah=4999, notified_price_uah=4999)
    result = monitor._detect_change(stored, new_price=499, new_original=4999, new_discount=90, discount_threshold=90)
    assert result == "big_discount"


def test_big_discount_below_threshold():
    monitor = make_monitor()
    stored = _stored(price_uah=4999, original_price_uah=4999, notified_price_uah=4999)
    result = monitor._detect_change(stored, new_price=2499, new_original=4999, new_discount=50, discount_threshold=90)
    assert result is None


def test_big_discount_already_notified_same_price():
    monitor = make_monitor()
    stored = _stored(price_uah=499, original_price_uah=4999, notified_price_uah=499)
    result = monitor._detect_change(stored, new_price=499, new_original=4999, new_discount=90, discount_threshold=90)
    assert result is None


def test_big_discount_price_dropped_further():
    monitor = make_monitor()
    stored = _stored(price_uah=999, original_price_uah=4999, notified_price_uah=999)
    result = monitor._detect_change(stored, new_price=499, new_original=4999, new_discount=90, discount_threshold=90)
    assert result == "big_discount"


def test_always_free_skipped():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=None, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=0, new_original=None, new_discount=0, discount_threshold=90)
    assert result is None


def test_no_price_change():
    monitor = make_monitor()
    stored = _stored(price_uah=4999, original_price_uah=4999, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=4999, new_original=4999, new_discount=0, discount_threshold=90)
    assert result is None


# ── format_price_alert (EGS store) tests ──────────────────────────────────────

def test_became_free_egs_format():
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.epicgames.com/en-US/p/test-game",
        old_price_uah=4999,
        new_price_uah=0,
        original_price_uah=4999,
        discount_pct=100,
        alert_type="became_free",
        game_info=None,
        store="egs",
    )
    assert "безкоштовною" in msg
    assert "Epic Games Store" in msg
    assert "#free" in msg
    assert "#epic" in msg
    assert "Test Game" in msg


def test_big_discount_egs_format():
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.epicgames.com/en-US/p/test-game",
        old_price_uah=4999,
        new_price_uah=499,
        original_price_uah=4999,
        discount_pct=90,
        alert_type="big_discount",
        game_info=None,
        store="egs",
    )
    assert "знижка" in msg.lower()
    assert "90%" in msg
    assert "#знижка" in msg
    assert "#epic" in msg


def test_steam_format_unchanged():
    """Existing Steam alerts should still work (backward-compat)."""
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
    assert "Steam" in msg
    assert "#steam" in msg
    assert "Epic" not in msg


# ── cross-store block tests ────────────────────────────────────────────────────

def test_cross_store_block_included():
    """cross_store_data causes cross-store block to appear in message."""
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    cross_store_data = {
        "store": "steam",
        "url": "https://store.steampowered.com/app/123/",
        "price_uah": 499,
        "original_price_uah": 4999,
        "discount_pct": 90,
    }
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.epicgames.com/en-US/p/test-game",
        old_price_uah=4999,
        new_price_uah=499,
        original_price_uah=4999,
        discount_pct=90,
        alert_type="big_discount",
        game_info=None,
        store="egs",
        cross_store_data=cross_store_data,
    )
    assert "Також у Steam" in msg
    assert "store.steampowered.com" in msg
    assert "━━━━━━━━━━" in msg


def test_cross_store_block_egs_in_steam_message():
    """Steam alert can reference EGS in cross-store block."""
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    cross_store_data = {
        "store": "egs",
        "url": "https://store.epicgames.com/en-US/p/test-game",
        "price_uah": 499,
        "original_price_uah": 4999,
        "discount_pct": 90,
    }
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.steampowered.com/app/123/",
        old_price_uah=4999,
        new_price_uah=499,
        original_price_uah=4999,
        discount_pct=90,
        alert_type="big_discount",
        game_info=None,
        store="steam",
        cross_store_data=cross_store_data,
    )
    assert "Також в Epic Games Store" in msg
    assert "epicgames.com" in msg


def test_no_cross_store_block_without_data():
    """No cross_store_data → no separator block."""
    from src.bot.message_formatter import MessageFormatter
    formatter = MessageFormatter()
    msg = formatter.format_price_alert(
        name="Test Game",
        url="https://store.epicgames.com/en-US/p/test-game",
        old_price_uah=4999,
        new_price_uah=499,
        original_price_uah=4999,
        discount_pct=90,
        alert_type="big_discount",
        game_info=None,
        store="egs",
    )
    assert "━━━━━━━━━━" not in msg


# ── _process_result tests ──────────────────────────────────────────────────────

def test_process_result_sends_alert():
    monitor = make_monitor()

    stored = {
        "url_slug": "test-game",
        "name": "Test Game",
        "url": "https://store.epicgames.com/en-US/p/test-game",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": 4999,
        "discount_pct": 0,
        "key_image": None,
        "description": None,
    }
    monitor.storage.get_egs_game = AsyncMock(return_value=stored)

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(
        "test-game", "Test Game", "https://store.epicgames.com/en-US/p/test-game", price_data
    ))

    assert result is True
    monitor.storage.update_egs_notification.assert_called_once_with("test-game", 0)


def test_process_result_no_alert_no_change():
    monitor = make_monitor()

    stored = {
        "url_slug": "test-game",
        "name": "Test Game",
        "url": "https://store.epicgames.com/en-US/p/test-game",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": None,
        "discount_pct": 0,
        "key_image": None,
        "description": None,
    }
    monitor.storage.get_egs_game = AsyncMock(return_value=stored)

    price_data = {"price_uah": 4999, "original_price_uah": 4999, "discount_pct": 0}
    result = asyncio.run(monitor._process_result(
        "test-game", "Test Game", "https://store.epicgames.com/en-US/p/test-game", price_data
    ))

    assert result is False
    monitor.storage.update_egs_notification.assert_not_called()


def test_process_result_no_stored_game():
    monitor = make_monitor()
    monitor.storage.get_egs_game = AsyncMock(return_value=None)

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(
        "some-game", "Some Game", "https://store.epicgames.com/en-US/p/some-game", price_data
    ))

    assert result is False


def test_cross_store_data_included_when_steam_recent():
    """If Steam notified < 30 min ago, cross_store_data should be included in message."""
    monitor = make_monitor()

    stored = {
        "url_slug": "test-game",
        "name": "Test Game",
        "url": "https://store.epicgames.com/en-US/p/test-game",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": 4999,
        "discount_pct": 0,
        "key_image": None,
        "description": None,
    }
    monitor.storage.get_egs_game = AsyncMock(return_value=stored)

    recent_notified_at = (datetime.now() - timedelta(minutes=10)).isoformat()
    steam_row = {
        "appid": 123,
        "name": "Test Game",
        "url": "https://store.steampowered.com/app/123/",
        "price_uah": 499,
        "original_price_uah": 4999,
        "discount_pct": 90,
        "notified_at": recent_notified_at,
        "notified_price_uah": 499,
    }
    monitor.storage.find_steam_game_by_name = AsyncMock(return_value=steam_row)

    sent_messages = []

    async def capture_send(msg, images=None):
        sent_messages.append(msg)
        return True

    monitor.bot.send_message = capture_send

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(
        "test-game", "Test Game", "https://store.epicgames.com/en-US/p/test-game", price_data
    ))

    assert result is True
    assert sent_messages
    msg = sent_messages[0]
    assert "Також у Steam" in msg
    assert "store.steampowered.com" in msg


def test_cross_store_data_not_included_when_steam_old():
    """If Steam notified > 30 min ago, cross_store_data should NOT be included."""
    monitor = make_monitor()

    stored = {
        "url_slug": "test-game",
        "name": "Test Game",
        "url": "https://store.epicgames.com/en-US/p/test-game",
        "price_uah": 4999,
        "original_price_uah": 4999,
        "notified_price_uah": 4999,
        "discount_pct": 0,
        "key_image": None,
        "description": None,
    }
    monitor.storage.get_egs_game = AsyncMock(return_value=stored)

    old_notified_at = (datetime.now() - timedelta(hours=2)).isoformat()
    steam_row = {
        "appid": 123,
        "name": "Test Game",
        "url": "https://store.steampowered.com/app/123/",
        "price_uah": 499,
        "original_price_uah": 4999,
        "discount_pct": 90,
        "notified_at": old_notified_at,
        "notified_price_uah": 499,
    }
    monitor.storage.find_steam_game_by_name = AsyncMock(return_value=steam_row)

    sent_messages = []

    async def capture_send(msg, images=None):
        sent_messages.append(msg)
        return True

    monitor.bot.send_message = capture_send

    price_data = {"price_uah": 0, "original_price_uah": 4999, "discount_pct": 100}
    asyncio.run(monitor._process_result(
        "test-game", "Test Game", "https://store.epicgames.com/en-US/p/test-game", price_data
    ))

    if sent_messages:
        assert "━━━━━━━━━━" not in sent_messages[0]
