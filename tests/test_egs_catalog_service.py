"""Tests for EgsCatalogService (Epic GraphQL-backed)."""

import asyncio
from unittest.mock import MagicMock

from src.services.egs_catalog_service import EgsCatalogService


def _service():
    return EgsCatalogService()


# ── Mock helpers ───────────────────────────────────────────────────────────────

def _make_element(title, slug, original, current, discount_pct):
    """discount_pct is %, stored as absolute cents in EGS API (original * pct / 100)."""
    discount_abs = round(original * discount_pct / 100)
    return {
        "title": title,
        "productSlug": slug,
        "urlSlug": slug,
        "price": {
            "totalPrice": {
                "originalPrice": original,
                "discountPrice": current,
                "discount": discount_abs,
            }
        },
    }


def _make_page_response(elements, total):
    return {
        "data": {
            "Catalog": {
                "searchStore": {
                    "paging": {"total": total, "count": len(elements)},
                    "elements": elements,
                }
            }
        }
    }


# ── _parse_game tests ──────────────────────────────────────────────────────────

def test_parse_game_discount():
    # original=5000, current=500, discount_abs=4500 → discount_pct=90
    element = _make_element("Witcher 3", "the-witcher-3", 5000, 500, 90)
    result = EgsCatalogService._parse_game(element)
    assert result is not None
    slug, data = result
    assert slug == "the-witcher-3"
    assert data["name"] == "Witcher 3"
    assert data["price_usd"] == 500
    assert data["original_price_usd"] == 5000
    assert data["discount_pct"] == 90
    assert data["url"] == "https://store.epicgames.com/en-US/p/the-witcher-3"


def test_parse_game_free():
    """F2P game (original == 0) → None."""
    element = _make_element("Free Game", "free-game", 0, 0, 0)
    result = EgsCatalogService._parse_game(element)
    assert result is None


def test_parse_game_became_free():
    """Game that was paid but is now free → keep (original > 0)."""
    element = _make_element("Sale Game", "sale-game", 3000, 0, 100)
    result = EgsCatalogService._parse_game(element)
    assert result is not None
    slug, data = result
    assert data["original_price_usd"] == 3000
    assert data["price_usd"] == 0
    assert data["discount_pct"] == 100


def test_parse_game_no_slug():
    """Element without slug → None."""
    element = {
        "title": "No Slug Game",
        "productSlug": "",
        "urlSlug": "",
        "price": {"totalPrice": {"originalPrice": 999, "discountPrice": 99, "discount": 90}},
    }
    result = EgsCatalogService._parse_game(element)
    assert result is None


# ── scan_all_prices tests ──────────────────────────────────────────────────────

def test_scan_pagination():
    """Two pages: total=50, page_size=40 → two fetches."""
    service = _service()

    page0_elements = [_make_element(f"Game {i}", f"game-{i}", 1000, 100, 90) for i in range(40)]
    page1_elements = [_make_element(f"Game {i}", f"game-{i}", 1000, 100, 90) for i in range(40, 50)]

    call_count = [0]

    async def mock_fetch_page(start: int) -> dict:
        call_count[0] += 1
        if start == 0:
            return _make_page_response(page0_elements, total=50)
        elif start == 40:
            return _make_page_response(page1_elements, total=50)
        return _make_page_response([], total=50)

    service._fetch_page = mock_fetch_page

    results = {}

    def cb(slug, data):
        results[slug] = data

    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    total = asyncio.run(fast_run())
    assert total == 50
    assert call_count[0] == 2
    assert "game-0" in results
    assert "game-49" in results


def test_scan_empty():
    """Empty first page → 0 processed."""
    service = _service()

    async def mock_fetch_page(start: int) -> dict:
        return _make_page_response([], total=0)

    service._fetch_page = mock_fetch_page
    results = {}

    def cb(slug, data):
        results[slug] = data

    total = asyncio.run(service.scan_all_prices(cb))
    assert total == 0
    assert results == {}


def test_scan_skips_f2p():
    """F2P games (original=0) are not included in results."""
    service = _service()

    elements = [
        _make_element("Paid Game", "paid-game", 999, 99, 90),
        _make_element("F2P Game", "f2p-game", 0, 0, 0),
    ]

    async def mock_fetch_page(start: int) -> dict:
        if start == 0:
            return _make_page_response(elements, total=2)
        return _make_page_response([], total=2)

    service._fetch_page = mock_fetch_page
    results = {}

    def cb(slug, data):
        results[slug] = data

    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    total = asyncio.run(fast_run())
    assert total == 1
    assert "paid-game" in results
    assert "f2p-game" not in results


def test_scan_stops_on_error():
    """Network error on page 2 → stops scan, returns count from page 1 only."""
    service = _service()

    page0_elements = [_make_element(f"Game {i}", f"game-{i}", 1000, 100, 90) for i in range(40)]

    async def mock_fetch_page(start: int) -> dict:
        if start == 0:
            return _make_page_response(page0_elements, total=80)
        raise RuntimeError("network error")

    service._fetch_page = mock_fetch_page
    results = {}

    def cb(slug, data):
        results[slug] = data

    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    total = asyncio.run(fast_run())
    assert total == 40
