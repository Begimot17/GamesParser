"""Tests for SteamCatalogService (Steam Store Search HTML backed)."""

import asyncio

from src.services.steam_catalog_service import SteamCatalogService


def _service():
    return SteamCatalogService()


# ── HTML mock helpers ──────────────────────────────────────────────────────────

def _make_row(appid: int, name: str, price_final: int, discount: int) -> str:
    # Mirrors real Steam HTML: <a href="...app/APPID/..."> comes first,
    # followed by class="search_result_row", then price attributes inside.
    return (
        f'<a href="https://store.steampowered.com/app/{appid}/" '
        f'data-ds-appid="{appid}" '
        f'class="search_result_row ds_collapse_flag">'
        f'<span class="title">{name}</span>'
        f'<div data-price-final="{price_final}" '
        f'data-bundlediscount="0" data-discount="{discount}"></div>'
        f'</a>'
    )


def _make_html(rows: list, total: int) -> str:
    rows_html = "".join(_make_row(r["appid"], r["name"], r["price_final"], r["discount"]) for r in rows)
    return f'{total:,} results match your search.\n{rows_html}'


ROWS_PAGE_0 = [
    {"appid": 292030, "name": "The Witcher 3", "price_final": 49900, "discount": 80},
    {"appid": 1091500, "name": "Cyberpunk 2077", "price_final": 124900, "discount": 50},
]

ROWS_PAGE_1 = [
    {"appid": 570, "name": "Dota 2", "price_final": 0, "discount": 0},
]


def test_parse_total():
    assert SteamCatalogService._parse_total("7,896 results match your search.") == 7896


def test_parse_total_not_found():
    assert SteamCatalogService._parse_total("no results here") == 0


def test_parse_results_html_paid_game():
    html = _make_html(ROWS_PAGE_0[:1], total=1)
    results = SteamCatalogService._parse_results_html(html)
    assert len(results) == 1
    r = results[0]
    assert r["appid"] == 292030
    assert r["name"] == "The Witcher 3"
    assert r["price_uah"] == 49900
    assert r["discount_pct"] == 80
    assert r["original_price_uah"] == 249500  # 49900*100/20


def test_parse_results_html_zero_price():
    html = _make_html(ROWS_PAGE_1, total=1)
    results = SteamCatalogService._parse_results_html(html)
    assert len(results) == 1
    r = results[0]
    assert r["price_uah"] == 0
    assert r["original_price_uah"] is None


def test_parse_results_html_empty():
    assert SteamCatalogService._parse_results_html("") == []


def test_parse_results_html_multiple():
    html = _make_html(ROWS_PAGE_0, total=2)
    results = SteamCatalogService._parse_results_html(html)
    assert len(results) == 2
    appids = {r["appid"] for r in results}
    assert 292030 in appids and 1091500 in appids


def test_parse_results_html_original_calculated():
    row = {"appid": 1, "name": "Game", "price_final": 70000, "discount": 30}
    html = _make_html([row], total=1)
    results = SteamCatalogService._parse_results_html(html)
    assert results[0]["original_price_uah"] == 100000  # 70000*100/70


def test_scan_all_prices_paginates():
    service = _service()
    responses = {
        0: _make_html(ROWS_PAGE_0, total=200),
        100: _make_html(ROWS_PAGE_1, total=200),
        200: "",
    }
    async def mock_fetch_page(start): return responses.get(start, "")
    service._fetch_page = mock_fetch_page
    results = {}
    def cb(appid, data): results[appid] = data
    async def run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)
    total = asyncio.run(run())
    assert total == 3
    assert 292030 in results and 570 in results


def test_scan_all_prices_uah():
    service = _service()
    async def mock_fetch_page(start): return _make_html(ROWS_PAGE_0[:1], total=1) if start == 0 else ""
    service._fetch_page = mock_fetch_page
    results = {}
    def cb(appid, data): results[appid] = data
    async def run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)
    asyncio.run(run())
    assert results[292030]["price_uah"] == 49900
    assert results[292030]["discount_pct"] == 80
    assert results[292030]["original_price_uah"] == 249500


def test_scan_stops_on_error():
    service = _service()
    async def mock_fetch_page(start):
        if start == 0: return _make_html(ROWS_PAGE_0, total=200)
        raise RuntimeError("err")
    service._fetch_page = mock_fetch_page
    results = {}
    def cb(appid, data): results[appid] = data
    async def run():
        import unittest.mock as m
        with m.patch("asyncio.sleep"):
            return await service.scan_all_prices(cb)
    total = asyncio.run(run())
    assert total == 2


def test_scan_stops_empty():
    service = _service()
    async def mock_fetch_page(start): return ""
    service._fetch_page = mock_fetch_page
    results = {}
    def cb(appid, data): results[appid] = data
    total = asyncio.run(service.scan_all_prices(cb))
    assert total == 0 and results == {}
