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
    storage.find_egs_game_by_name = AsyncMock(return_value=None)

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)

    monitor = SteamPriceMonitor(storage=storage, bot=bot)
    monitor.price_service.get_steam_info = AsyncMock(return_value=None)
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
    result = monitor._detect_change(stored, new_price=0, new_original=49900, new_discount=100, discount_threshold=50)
    assert result == "became_free"


def test_became_free_already_notified():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=49900, notified_price_uah=0)
    result = monitor._detect_change(stored, new_price=0, new_original=49900, new_discount=100, discount_threshold=50)
    assert result is None


def test_big_discount():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90, discount_threshold=50)
    assert result == "big_discount"


def test_big_discount_below_min_threshold():
    # 49% discount is below the lowest possible threshold (50%) → _detect_change returns None
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=25449, new_original=49900, new_discount=49, discount_threshold=50)
    assert result is None


def test_big_discount_at_min_threshold_passes_detect_change():
    # 50% discount passes the pre-filter in _detect_change (quality gate is checked later)
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=49900)
    result = monitor._detect_change(stored, new_price=24950, new_original=49900, new_discount=50, discount_threshold=50)
    assert result == "big_discount"


def test_big_discount_already_notified_same_price():
    monitor = make_monitor()
    stored = _stored(price_uah=4990, original_price_uah=49900, notified_price_uah=4990)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90, discount_threshold=50)
    assert result is None


def test_big_discount_price_dropped_further():
    monitor = make_monitor()
    # Was at 9900 (80% off), now dropped to 4990 (90% off) — price changed → alert
    stored = _stored(price_uah=9900, original_price_uah=49900, notified_price_uah=9900)
    result = monitor._detect_change(stored, new_price=4990, new_original=49900, new_discount=90, discount_threshold=50)
    assert result == "big_discount"


def test_always_free_skipped():
    monitor = make_monitor()
    stored = _stored(price_uah=0, original_price_uah=None, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=0, new_original=None, new_discount=0, discount_threshold=50)
    assert result is None


def test_no_price_change():
    monitor = make_monitor()
    stored = _stored(price_uah=49900, original_price_uah=49900, notified_price_uah=None)
    result = monitor._detect_change(stored, new_price=49900, new_original=49900, new_discount=0, discount_threshold=50)
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
    assert "Бесплатно" in msg
    assert "₴49" in msg  # UAH price (4999 kopecks = ₴49)
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
    assert "скидка" in msg.lower()
    assert "90%" in msg
    assert "#скидка" in msg
    assert "#steam" in msg
    assert "Test Game" in msg
    assert "₴" in msg  # UAH symbol


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


# ── _compute_quality_score tests ──────────────────────────────────────────────

def test_quality_score_none_game_info():
    # No game_info → fallback score 15
    assert SteamPriceMonitor._compute_quality_score(None) == 15


def test_quality_score_overwhelmingly_positive():
    from src.services.price_service import GameInfo
    info = GameInfo(review_score="Overwhelmingly Positive", recommendations_total=200_000, metacritic=86)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 50 + 30 + 20  # 100


def test_quality_score_very_positive_high_recs():
    from src.services.price_service import GameInfo
    # Very Positive (40) + 200k recs (30) + Metacritic 86 (20) = 90 → threshold 50%
    info = GameInfo(review_score="Very Positive", recommendations_total=200_000, metacritic=86)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 90


def test_quality_score_mostly_positive_low_recs():
    from src.services.price_service import GameInfo
    # Mostly Positive (25) + 5k recs (12) + no metacritic = 37 → score < 40 → suppressed
    info = GameInfo(review_score="Mostly Positive", recommendations_total=5_000)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 37


def test_quality_score_no_reviews():
    from src.services.price_service import GameInfo
    # No review_score, 50 recs (<100) → 0+0+0 = 0 → threshold None (suppress)
    info = GameInfo(recommendations_total=50)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 0


def test_quality_score_mixed():
    from src.services.price_service import GameInfo
    info = GameInfo(review_score="Mixed", recommendations_total=0)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 5


def test_quality_score_negative_review():
    from src.services.price_service import GameInfo
    info = GameInfo(review_score="Mostly Negative", recommendations_total=500, metacritic=45)
    score = SteamPriceMonitor._compute_quality_score(info)
    assert score == 0 + 5 + 0  # 5


# ── _quality_adjusted_threshold tests ─────────────────────────────────────────

def test_threshold_score_80_plus():
    monitor = make_monitor()
    from src.services.price_service import GameInfo
    info = GameInfo(review_score="Overwhelmingly Positive", recommendations_total=200_000, metacritic=86)
    assert monitor._quality_adjusted_threshold(info) == 65  # score=100 → tier >= 80 → 65%


def test_threshold_score_below_10_suppressed():
    monitor = make_monitor()
    from src.services.price_service import GameInfo
    info = GameInfo(recommendations_total=50)  # score=5 < 40 → suppress
    assert monitor._quality_adjusted_threshold(info) is None


def test_threshold_score_10_to_19():
    monitor = make_monitor()
    # score=15 (no game_info fallback) < 40 → suppress
    assert monitor._quality_adjusted_threshold(None) is None


# ── quality gate integration in _process_result ───────────────────────────────

def test_process_result_suppressed_low_quality():
    """70% discount + score < 10 → alert suppressed."""
    from src.services.price_service import GameInfo
    monitor = make_monitor()

    stored = {
        "appid": 999,
        "name": "Unknown Asset",
        "price_uah": 49900,
        "original_price_uah": 49900,
        "notified_price_uah": 49900,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)
    monitor.price_service.get_steam_info = AsyncMock(
        return_value=GameInfo(recommendations_total=50)  # score=5 → threshold None
    )

    price_data = {"price_uah": 14970, "original_price_uah": 49900, "discount_pct": 70}
    result = asyncio.run(monitor._process_result(999, "Unknown Asset", price_data))

    assert result is False
    monitor.storage.update_steam_notification.assert_not_called()


def test_process_result_became_free_bypasses_quality():
    """became_free alert bypasses quality gate regardless of score."""
    from src.services.price_service import GameInfo
    monitor = make_monitor()

    stored = {
        "appid": 999,
        "name": "Unknown Asset",
        "price_uah": 49900,
        "original_price_uah": 49900,
        "notified_price_uah": 49900,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)
    monitor.price_service.get_steam_info = AsyncMock(
        return_value=GameInfo(recommendations_total=0)  # score=0 → would be suppressed
    )

    price_data = {"price_uah": 0, "original_price_uah": 49900, "discount_pct": 100}
    result = asyncio.run(monitor._process_result(999, "Unknown Asset", price_data))

    assert result is True
    monitor.storage.update_steam_notification.assert_called_once_with(999, 0)


def test_process_result_high_quality_65pct_passes():
    """Very Positive + 200k recs + Metacritic 86 → score=90 ≥ 80 → threshold 65% → 70% passes."""
    from src.services.price_service import GameInfo
    monitor = make_monitor()

    stored = {
        "appid": 1091500,
        "name": "Cyberpunk 2077",
        "price_uah": 139900,
        "original_price_uah": 139900,
        "notified_price_uah": 139900,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)
    monitor.price_service.get_steam_info = AsyncMock(
        return_value=GameInfo(
            review_score="Very Positive",
            recommendations_total=200_000,
            metacritic=86,
        )
    )

    price_data = {"price_uah": 41970, "original_price_uah": 139900, "discount_pct": 70}
    result = asyncio.run(monitor._process_result(1091500, "Cyberpunk 2077", price_data))

    assert result is True


def test_process_result_high_quality_50pct_blocked():
    """Same game with only 50% discount → below new 65% threshold → suppressed."""
    from src.services.price_service import GameInfo
    monitor = make_monitor()

    stored = {
        "appid": 1091500,
        "name": "Cyberpunk 2077",
        "price_uah": 139900,
        "original_price_uah": 139900,
        "notified_price_uah": 139900,
        "discount_pct": 0,
    }
    monitor.storage.get_steam_game = AsyncMock(return_value=stored)
    monitor.price_service.get_steam_info = AsyncMock(
        return_value=GameInfo(
            review_score="Very Positive",
            recommendations_total=200_000,
            metacritic=86,
        )
    )

    price_data = {"price_uah": 69950, "original_price_uah": 139900, "discount_pct": 50}
    result = asyncio.run(monitor._process_result(1091500, "Cyberpunk 2077", price_data))

    assert result is False
