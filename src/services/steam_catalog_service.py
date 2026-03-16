"""Steam catalog scanning service for price monitoring (via SteamSpy)."""

import asyncio
from typing import Callable, Optional

import aiohttp

from src.common.logger import logger

STEAMSPY_API_URL = "https://steamspy.com/api.php"
TIMEOUT = aiohttp.ClientTimeout(total=30)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
PAGE_DELAY = 1.0        # seconds between SteamSpy pages (rate limit)
MAX_PAGES = 200         # safety cap (~70k games at 1000/page)


class SteamCatalogService:
    """Fetches Steam catalog and prices via SteamSpy (no auth required).

    Prices are in USD cents (e.g. 999 = $9.99).
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

    # ── SteamSpy helpers ──────────────────────────────────────────────────

    async def _fetch_page(self, page: int) -> dict:
        """Fetch one page from SteamSpy (1000 games per page)."""
        session = await self._get_session()
        params = {"request": "all", "page": page}
        async with session.get(STEAMSPY_API_URL, params=params, timeout=TIMEOUT, headers=HEADERS) as resp:
            if resp.status != 200:
                raise RuntimeError(f"SteamSpy page {page} returned HTTP {resp.status}")
            return await resp.json(content_type=None)

    @staticmethod
    def _parse_price(info: dict) -> dict:
        """Parse SteamSpy game record into price_data dict.

        Returns:
            name            : str
            price_uah       : int   — final price, USD cents
            original_price_uah : int | None — original price, USD cents;
                                              None means always-free (F2P)
            discount_pct    : int   — discount %
        """
        def to_int(v) -> int:
            try:
                return int(v) if v else 0
            except (ValueError, TypeError):
                return 0

        price = to_int(info.get("price"))
        initial = to_int(info.get("initialprice"))
        discount = to_int(info.get("discount"))

        # If initial == 0 and discount == 0 → always free (F2P) → skip in monitor
        original = initial if initial > 0 else None

        return {
            "name": info.get("name", ""),
            "price_uah": price,
            "original_price_uah": original,
            "discount_pct": discount,
        }

    # ── Public API ────────────────────────────────────────────────────────

    async def get_app_list(self) -> list[dict]:
        """Return list of {appid, name} by reading the first SteamSpy page.

        For a full catalog scan prefer scan_all_prices() which is more efficient.
        """
        try:
            data = await self._fetch_page(0)
            return [
                {"appid": int(k), "name": v.get("name", "")}
                for k, v in data.items()
                if k.isdigit()
            ]
        except Exception as e:
            logger.error("[SteamCatalog] get_app_list failed: %s", e)
            return []

    async def scan_all_prices(
        self,
        on_result_cb: Callable[[int, dict], None],
    ) -> int:
        """Paginate through all SteamSpy games and call on_result_cb for each.

        on_result_cb(appid, price_data) where price_data contains:
            name, price_uah (USD cents), original_price_uah (USD cents | None), discount_pct

        Returns total number of games processed.
        """
        total = 0
        for page in range(MAX_PAGES):
            try:
                data = await self._fetch_page(page)
            except Exception as e:
                logger.warning("[SteamCatalog] Page %d failed: %s — stopping scan", page, e)
                break

            if not data:
                logger.info("[SteamCatalog] Scan complete: page %d empty, %d total games", page, total)
                break

            for appid_str, info in data.items():
                if not appid_str.isdigit():
                    continue
                price_data = self._parse_price(info)
                on_result_cb(int(appid_str), price_data)
                total += 1

            logger.info("[SteamCatalog] Page %d: %d games (total: %d)", page, len(data), total)
            await asyncio.sleep(PAGE_DELAY)

        return total
