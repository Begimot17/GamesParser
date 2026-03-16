"""EGS catalog scanning service for price monitoring (via Epic GraphQL API)."""

import asyncio
from typing import Callable, Optional

import cloudscraper

from src.common.logger import logger

EGS_GRAPHQL_URL = "https://store.epicgames.com/graphql"
PAGE_SIZE = 40

# Named operation so APQ / CDN caching can work; uses variables rather than
# string interpolation to avoid any injection issues.
_QUERY = """
query searchStoreQuery(
  $allowCountries: String,
  $count: Int,
  $country: String!,
  $locale: String,
  $start: Int,
  $onSale: Boolean
) {
  Catalog {
    searchStore(
      allowCountries: $allowCountries,
      count: $count,
      country: $country,
      locale: $locale,
      start: $start,
      onSale: $onSale
    ) {
      paging { total count }
      elements {
        title
        productSlug
        urlSlug
        price(country: $country) {
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

    Uses cloudscraper to bypass Cloudflare protection.
    Prices are returned in the store's local currency cents (UA → UAH kopecks).
    Field names intentionally mirror SteamCatalogService (price_usd = local cents).
    """

    def __init__(self):
        # cloudscraper is synchronous; calls are wrapped in asyncio.to_thread
        self._session: Optional[cloudscraper.CloudScraper] = None

    def _get_session(self) -> cloudscraper.CloudScraper:
        if self._session is None:
            self._session = cloudscraper.create_scraper()
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _fetch_page_sync(self, start: int) -> dict:
        """Synchronous POST to EGS GraphQL (called via asyncio.to_thread)."""
        session = self._get_session()
        variables = {
            "allowCountries": "UA",
            "count": PAGE_SIZE,
            "country": "UA",
            "locale": "uk",
            "start": start,
            "onSale": True,
        }
        resp = session.post(
            EGS_GRAPHQL_URL,
            json={"query": _QUERY, "variables": variables},
            headers={"content-type": "application/json;charset=UTF-8"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"EGS GraphQL start={start} returned HTTP {resp.status_code}")
        return resp.json()

    async def _fetch_page(self, start: int) -> dict:
        """Async wrapper around the synchronous fetch."""
        return await asyncio.to_thread(self._fetch_page_sync, start)

    @staticmethod
    def _parse_game(element: dict) -> tuple[str, dict] | None:
        """Parse a single EGS catalog element into (url_slug, price_data).

        Returns None for F2P games (originalPrice == 0).
        The 'discount' field in the EGS response is an absolute amount in cents,
        not a percentage — we compute discount_pct here.
        """
        try:
            slug = (element.get("productSlug") or element.get("urlSlug") or "").strip()
            if not slug:
                return None

            title = element.get("title") or ""
            price_block = (element.get("price") or {}).get("totalPrice") or {}

            original = price_block.get("originalPrice") or 0
            current = price_block.get("discountPrice") or 0
            discount_abs = price_block.get("discount") or 0  # absolute cents, not %

            # F2P: original price is 0 → skip
            if original == 0:
                return None

            discount_pct = round(discount_abs / original * 100) if original > 0 else 0

            url = f"https://store.epicgames.com/en-US/p/{slug}"
            return slug, {
                "name": title,
                "price_usd": current,
                "original_price_usd": original,
                "discount_pct": discount_pct,
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
            name, price_usd (local cents), original_price_usd (local cents),
            discount_pct, url

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
