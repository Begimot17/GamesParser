"""Steam catalog scanning service for price monitoring (via Steam Store Search HTML)."""

import asyncio
import html as html_module
import re
from typing import Callable, Optional

import aiohttp

from src.common.logger import logger

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
PAGE_SIZE = 100
PAGE_DELAY = 0.5  # seconds between pages
TIMEOUT = aiohttp.ClientTimeout(total=30)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Regex patterns for parsing Steam search results HTML
# Attributes found in actual Steam HTML response (cc=ua):
#   data-ds-appid     — on the <a> row element
#   data-price-final  — final price in UAH kopecks
#   data-discount     — discount % (integer, e.g. 30 for -30%)
#   <span class="title"> — game name

_ROW_START_PAT = re.compile(r'<a\s[^>]*href="https://store\.steampowered\.com/app/(\d+)/')
_TITLE_PAT = re.compile(r'<span class="title">(.*?)</span>', re.DOTALL)
_PRICE_FINAL_PAT = re.compile(r'data-price-final="(\d+)"')
_DISCOUNT_PAT = re.compile(r'\bdata-discount="(\d+)"')
_TOTAL_PAT = re.compile(r'([\d,\u00a0]+)\s+results? match')


class SteamCatalogService:
    """Fetches on-sale Steam games and UAH prices via Steam Store Search HTML.

    Uses cc=ua&specials=1 to get only discounted games with real UAH prices.
    Prices are in UAH kopecks (e.g. 209900 = ₴2 099).
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Steam Store Search ────────────────────────────────────────────────

    async def _fetch_page(self, start: int) -> str:
        """Fetch one page from Steam Store Search (returns HTML string)."""
        session = await self._get_session()
        params = {
            "query": "",
            "start": start,
            "count": PAGE_SIZE,
            "cc": "ua",
            "specials": 1,
        }
        async with session.get(
            STEAM_SEARCH_URL, params=params, timeout=TIMEOUT, headers=HEADERS
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Steam search start={start} returned HTTP {resp.status}")
            return await resp.text()

    @staticmethod
    def _parse_total(html: str) -> int:
        """Extract total result count from HTML ('7,896 results match')."""
        m = _TOTAL_PAT.search(html)
        if not m:
            return 0
        return int(re.sub(r"[,\s\u00a0]", "", m.group(1)))

    @staticmethod
    def _parse_results_html(html: str) -> list[dict]:
        """Parse Steam search results HTML into list of price dicts.

        Returns list of dicts with keys:
            appid, name, price_uah (kopecks), original_price_uah (kopecks|None), discount_pct

        NOTE: We split by <a href="...store.../app/APPID/"> rather than by
        class="search_result_row" because in Steam HTML the data-ds-appid attribute
        appears BEFORE class="search_result_row" in the same <a> tag. Splitting by
        class would put each game's appid into the wrong chunk (the previous game's
        chunk), causing appid/name/price mismatches in the parsed output.
        """
        results = []
        # Find start positions and appids from the <a href> URL
        positions = [
            (m.start(), int(m.group(1)))
            for m in _ROW_START_PAT.finditer(html)
        ]

        for i, (start, appid) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(html)
            chunk = html[start:end]

            # Skip non-game-result anchors (e.g. header/footer links)
            if "search_result_row" not in chunk:
                continue

            m_title = _TITLE_PAT.search(chunk)
            name = html_module.unescape(m_title.group(1).strip()) if m_title else ""

            m_final = _PRICE_FINAL_PAT.search(chunk)
            price_uah = int(m_final.group(1)) if m_final else 0

            m_discount = _DISCOUNT_PAT.search(chunk)
            discount_pct = int(m_discount.group(1)) if m_discount else 0

            # Calculate original price from final and discount
            if discount_pct > 0 and discount_pct < 100 and price_uah > 0:
                original_price_uah = round(price_uah * 100 / (100 - discount_pct))
            elif discount_pct == 100 and price_uah == 0:
                # Became free — mark as original unknown (will be treated as F2P)
                original_price_uah = None
            else:
                original_price_uah = price_uah if price_uah > 0 else None

            results.append({
                "appid": appid,
                "name": name,
                "price_uah": price_uah,
                "original_price_uah": original_price_uah,
                "discount_pct": discount_pct,
            })
        return results

    # ── Public API ────────────────────────────────────────────────────────

    async def scan_all_prices(
        self,
        on_result_cb: Callable[[int, dict], None],
    ) -> int:
        """Paginate through on-sale Steam games and call on_result_cb for each.

        on_result_cb(appid, price_data) where price_data contains:
            name, price_uah (UAH kopecks), original_price_uah (UAH kopecks | None), discount_pct

        Returns total number of games processed.
        """
        total_processed = 0
        start = 0
        total_available = 0

        while True:
            try:
                html = await self._fetch_page(start)
            except Exception as e:
                logger.warning("[SteamCatalog] Page start=%d failed: %s — stopping scan", start, e)
                break

            if not html.strip():
                logger.info("[SteamCatalog] Scan complete: start=%d empty, %d total games", start, total_processed)
                break

            # Extract total on first page
            if start == 0:
                total_available = self._parse_total(html)
                logger.info("[SteamCatalog] Total on-sale games: %d", total_available)

            items = self._parse_results_html(html)
            if not items:
                logger.info("[SteamCatalog] Scan complete: no items parsed at start=%d", start)
                break

            for item in items:
                price_data = {
                    "name": item["name"],
                    "price_uah": item["price_uah"],
                    "original_price_uah": item["original_price_uah"],
                    "discount_pct": item["discount_pct"],
                }
                on_result_cb(item["appid"], price_data)
                total_processed += 1

            logger.info(
                "[SteamCatalog] start=%d: %d games parsed, total available=%d, processed=%d",
                start, len(items), total_available, total_processed,
            )

            start += PAGE_SIZE
            if total_available and start >= total_available:
                logger.info("[SteamCatalog] Scan complete: processed %d games", total_processed)
                break

            await asyncio.sleep(PAGE_DELAY)

        return total_processed
