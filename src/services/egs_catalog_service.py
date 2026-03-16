"""EGS catalog scanning service for price monitoring (via Epic GraphQL API)."""

import asyncio
from typing import Callable, Optional

import aiohttp

from src.common.logger import logger

EGS_GRAPHQL_URL = "https://graphql.epicgames.com/graphql"
PAGE_SIZE = 40
TIMEOUT = aiohttp.ClientTimeout(total=30)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
}

_QUERY = """
{
  Catalog {
    searchStore(
      onSale: true
      count: %(count)d
      start: %(start)d
      country: "UA"
      locale: "uk"
    ) {
      paging { total count }
      elements {
        title
        productSlug
        urlSlug
        price(country: "UA") {
          totalPrice {
            discountPrice
            originalPrice
            discount
          }
        }
      }
    }
  }
}
"""


class EgsCatalogService:
    """Fetches EGS catalog and on-sale prices via Epic GraphQL API.

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

    async def _fetch_page(self, start: int) -> dict:
        """POST one page to EGS GraphQL (PAGE_SIZE games)."""
        session = await self._get_session()
        query = _QUERY % {"count": PAGE_SIZE, "start": start}
        payload = {"query": query}
        async with session.post(EGS_GRAPHQL_URL, json=payload, timeout=TIMEOUT, headers=HEADERS) as resp:
            if resp.status != 200:
                raise RuntimeError(f"EGS GraphQL start={start} returned HTTP {resp.status}")
            return await resp.json(content_type=None)

    @staticmethod
    def _parse_game(element: dict) -> tuple[str, dict] | None:
        """Parse a single EGS catalog element into (url_slug, price_data).

        Returns None for F2P games (originalPrice == 0).
        """
        try:
            slug = (element.get("productSlug") or element.get("urlSlug") or "").strip()
            if not slug:
                return None

            title = element.get("title") or ""
            price_block = (element.get("price") or {}).get("totalPrice") or {}

            original = price_block.get("originalPrice") or 0
            current = price_block.get("discountPrice") or 0
            discount = price_block.get("discount") or 0

            # F2P: original price is 0 → skip
            if original == 0:
                return None

            url = f"https://store.epicgames.com/en-US/p/{slug}"
            return slug, {
                "name": title,
                "price_usd": current,
                "original_price_usd": original,
                "discount_pct": discount,
                "url": url,
            }
        except Exception:
            return None

    async def scan_all_prices(
        self,
        on_result_cb: Callable[[str, dict], None],
    ) -> int:
        """Paginate through all on-sale EGS games and call on_result_cb for each.

        on_result_cb(url_slug, price_data) where price_data contains:
            name, price_usd (USD cents), original_price_usd (USD cents), discount_pct, url

        Returns total number of games processed.
        """
        total_processed = 0
        start = 0

        while True:
            try:
                data = await self._fetch_page(start)
            except Exception as e:
                logger.warning("[EGSCatalog] Page start=%d failed: %s — stopping scan", start, e)
                break

            search_store = (
                (data.get("data") or {})
                .get("Catalog") or {}
            ).get("searchStore") or {}

            paging = search_store.get("paging") or {}
            total_available = paging.get("total") or 0
            elements = search_store.get("elements") or []

            if not elements:
                logger.info("[EGSCatalog] Scan complete: start=%d empty, %d total games", start, total_processed)
                break

            for element in elements:
                parsed = self._parse_game(element)
                if parsed is None:
                    continue
                slug, price_data = parsed
                on_result_cb(slug, price_data)
                total_processed += 1

            logger.info("[EGSCatalog] start=%d: %d elements, total available=%d, processed=%d",
                        start, len(elements), total_available, total_processed)

            start += PAGE_SIZE
            if total_available and start >= total_available:
                logger.info("[EGSCatalog] Scan complete: processed %d games", total_processed)
                break

            await asyncio.sleep(1.0)

        return total_processed
