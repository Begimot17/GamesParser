"""EGS catalog scanning service for price monitoring (via Epic GraphQL API)."""

import asyncio
import re
from typing import Callable, Optional

import cloudscraper

from src.common.logger import logger

EGS_GRAPHQL_URL = "https://store.epicgames.com/graphql"
PAGE_SIZE = 40

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
        description
        developerDisplayName
        offerMappings { pageSlug pageType }
        keyImages { type url }
        tags { name groupName }
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

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class EgsCatalogService:
    """Fetches EGS catalog and on-sale prices via Epic GraphQL API.

    Uses cloudscraper to bypass Cloudflare protection.
    Prices are returned in UAH kopecks (country=UA).
    """

    def __init__(self):
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
            "locale": "ru",
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
    def _pick_slug(element: dict) -> Optional[str]:
        """Pick the best URL slug for a game.

        Priority:
        1. offerMappings with pageType == 'productHome' → pageSlug
        2. productSlug
        3. urlSlug
        Returns None if nothing usable found.
        """
        for mapping in element.get("offerMappings") or []:
            if mapping.get("pageType") == "productHome":
                slug = (mapping.get("pageSlug") or "").strip()
                if slug:
                    return slug
        slug = (element.get("productSlug") or "").strip()
        if slug:
            return slug
        slug = (element.get("urlSlug") or "").strip()
        return slug if slug else None

    @staticmethod
    def _pick_key_image(element: dict) -> Optional[str]:
        """Return the best cover image URL from keyImages."""
        images = element.get("keyImages") or []
        # Prefer DieselStoreFrontWide (wide banner), fallback to first available
        for img in images:
            if img.get("type") == "DieselStoreFrontWide":
                return img.get("url")
        for img in images:
            url = img.get("url")
            if url:
                return url
        return None

    @staticmethod
    def _strip_html(text: str, max_len: int = 300) -> str:
        """Remove HTML tags and truncate."""
        plain = _HTML_TAG_RE.sub("", text or "").strip()
        return plain[:max_len] if len(plain) > max_len else plain

    @staticmethod
    def _parse_game(element: dict) -> tuple[str, dict] | None:
        """Parse a single EGS catalog element into (url_slug, price_data).

        Returns None for F2P games (originalPrice == 0) or missing slug.
        Prices are in UAH kopecks.
        """
        try:
            slug = EgsCatalogService._pick_slug(element)
            if not slug:
                return None

            title = element.get("title") or ""
            price_block = (element.get("price") or {}).get("totalPrice") or {}

            original = price_block.get("originalPrice") or 0
            current = price_block.get("discountPrice") or 0
            discount_abs = price_block.get("discount") or 0

            # F2P: original price is 0 → skip
            if original == 0:
                return None

            discount_pct = round(discount_abs / original * 100) if original > 0 else 0

            key_image = EgsCatalogService._pick_key_image(element)
            description = EgsCatalogService._strip_html(element.get("description") or "")
            developer = element.get("developerDisplayName") or ""

            # Parse tags
            tags = element.get("tags") or []
            genre_tags = [
                t["name"] for t in tags
                if t.get("groupName", "").lower() == "genre" and t.get("name")
            ][:3]
            feature_names = {
                t["name"].lower() for t in tags
                if t.get("groupName", "").lower() in ("feature", "features") and t.get("name")
            }
            has_controller = bool(feature_names & {
                "controller support", "full controller support", "partial controller support",
            })
            has_multiplayer = bool(feature_names & {
                "online multiplayer", "multiplayer", "co-op", "online co-op",
                "local multiplayer", "cross-platform multiplayer",
            })

            url = f"https://store.epicgames.com/en-US/p/{slug}"
            return slug, {
                "name": title,
                "price_uah": current,
                "original_price_uah": original,
                "discount_pct": discount_pct,
                "url": url,
                "key_image": key_image,
                "description": description,
                "developer": developer,
                "genre": ", ".join(genre_tags) if genre_tags else "",
                "has_controller_support": has_controller,
                "has_multiplayer": has_multiplayer,
            }
        except Exception:
            return None

    async def scan_all_prices(
        self,
        on_result_cb: Callable[[str, dict], None],
    ) -> int:
        """Paginate through all on-sale EGS games and call on_result_cb for each.

        on_result_cb(url_slug, price_data) where price_data contains:
            name, price_uah (UAH kopecks), original_price_uah (UAH kopecks),
            discount_pct, url, key_image, description

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
