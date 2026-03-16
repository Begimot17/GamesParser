"""Tests for SteamCatalogService (SteamSpy-backed)."""

import asyncio
from unittest.mock import MagicMock

from src.services.steam_catalog_service import SteamCatalogService


def _service():
    return SteamCatalogService()


# ── Mock helpers ──────────────────────────────────────────────────────────────

STEAMSPY_PAGE_0 = {
    "730": {"appid": 730, "name": "Counter-Strike 2", "price": "0", "initialprice": "0", "discount": "0"},
    "292030": {"appid": 292030, "name": "The Witcher 3", "price": "999", "initialprice": "4999", "discount": "80"},
    "1091500": {"appid": 1091500, "name": "Cyberpunk 2077", "price": "4999", "initialprice": "4999", "discount": "0"},
}

STEAMSPY_PAGE_1 = {
    "570": {"appid": 570, "name": "Dota 2", "price": "0", "initialprice": "0", "discount": "0"},
}

STEAMSPY_PAGE_2 = {}  # empty → end of pagination


class MockResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status = status

    async def json(self, content_type=None):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── _parse_price tests ────────────────────────────────────────────────────────

def test_parse_price_paid():
    result = SteamCatalogService._parse_price(
        {"name": "Witcher 3", "price": "999", "initialprice": "4999", "discount": "80"}
    )
    assert result["price_uah"] == 999
    assert result["original_price_uah"] == 4999
    assert result["discount_pct"] == 80
    assert result["name"] == "Witcher 3"


def test_parse_price_always_free():
    result = SteamCatalogService._parse_price(
        {"name": "CS2", "price": "0", "initialprice": "0", "discount": "0"}
    )
    assert result["price_uah"] == 0
    assert result["original_price_uah"] is None   # F2P → None
    assert result["discount_pct"] == 0


def test_parse_price_became_free():
    result = SteamCatalogService._parse_price(
        {"name": "Some Game", "price": "0", "initialprice": "4999", "discount": "100"}
    )
    assert result["price_uah"] == 0
    assert result["original_price_uah"] == 4999   # had a price → keep
    assert result["discount_pct"] == 100


def test_parse_price_missing_fields():
    result = SteamCatalogService._parse_price({"name": "X"})
    assert result["price_uah"] == 0
    assert result["original_price_uah"] is None
    assert result["discount_pct"] == 0


# ── get_app_list tests ────────────────────────────────────────────────────────

def test_get_app_list():
    service = _service()
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get.return_value = MockResponse(STEAMSPY_PAGE_0)
    service._session = mock_session

    apps = asyncio.run(service.get_app_list())
    assert len(apps) == 3
    appids = {a["appid"] for a in apps}
    assert 730 in appids
    assert 292030 in appids


def test_get_app_list_error():
    service = _service()
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get.return_value = MockResponse({}, status=500)
    service._session = mock_session

    apps = asyncio.run(service.get_app_list())
    assert apps == []


# ── scan_all_prices tests ─────────────────────────────────────────────────────

def test_scan_all_prices_paginates():
    service = _service()
    pages = [STEAMSPY_PAGE_0, STEAMSPY_PAGE_1, STEAMSPY_PAGE_2]

    call_count = [0]

    async def mock_fetch_page(page: int) -> dict:
        call_count[0] += 1
        return pages[page] if page < len(pages) else {}

    service._fetch_page = mock_fetch_page

    results = {}

    def cb(appid, data):
        results[appid] = data

    # Patch asyncio.sleep to skip waits
    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    total = asyncio.run(fast_run())

    assert total == 4  # 3 from page 0, 1 from page 1
    assert 730 in results
    assert 292030 in results
    assert 570 in results


def test_scan_all_prices_f2p_has_none_original():
    service = _service()

    async def mock_fetch_page(page: int) -> dict:
        if page == 0:
            return STEAMSPY_PAGE_0
        return {}

    service._fetch_page = mock_fetch_page

    results = {}

    def cb(appid, data):
        results[appid] = data

    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    asyncio.run(fast_run())

    # CS2 (730) is F2P → original_price_uah must be None
    assert results[730]["original_price_uah"] is None
    # Witcher 3 has a price
    assert results[292030]["original_price_uah"] == 4999


def test_scan_all_prices_stops_on_error():
    service = _service()

    async def mock_fetch_page(page: int) -> dict:
        if page == 0:
            return STEAMSPY_PAGE_0
        raise RuntimeError("network error")

    service._fetch_page = mock_fetch_page

    results = {}

    def cb(appid, data):
        results[appid] = data

    async def fast_run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)

    total = asyncio.run(fast_run())
    # Only page 0 processed, error on page 1 stops scan
    assert total == 3
