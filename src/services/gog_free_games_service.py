"""GOG free games catalog service."""

import asyncio
from typing import Optional

import aiohttp

from src.common.logger import logger

GOG_CATALOG_URL = "https://catalog.gog.com/v1/catalog"
PAGE_SIZE = 48
PAGE_DELAY = 1.0  # seconds between pages


class GogFreeGamesService:
    """Fetches permanently free games from GOG Catalog API."""

    PLATFORM = "gog"

    async def fetch_free_games(self) -> list[dict]:
        """Return list of free games: {id, name, url, image_url, description}."""
        results = []
        params_base = {
            "price": "between:0,0",
            "limit": PAGE_SIZE,
            "order": "desc:trend",
            "productType": "in:game,pack",
            "countryCode": "UA",
            "currencyCode": "UAH",
            "locale": "ru-RU",
        }

        async with aiohttp.ClientSession() as session:
            # First request to discover total pages
            params = {**params_base, "page": 1}
            try:
                async with session.get(GOG_CATALOG_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"GOG catalog returned HTTP {resp.status}")
                    data = await resp.json(content_type=None)
            except Exception as e:
                logger.error("[GOG] Failed to fetch page 1: %s", e)
                return []

            total_pages = data.get("pages", 1)
            results.extend(self._parse_products(data.get("products", [])))
            logger.info("[GOG] Page 1/%d: %d games found so far", total_pages, len(results))

            for page in range(2, total_pages + 1):
                await asyncio.sleep(PAGE_DELAY)
                params = {**params_base, "page": page}
                try:
                    async with session.get(GOG_CATALOG_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            logger.warning("[GOG] Page %d returned HTTP %d, skipping", page, resp.status)
                            continue
                        data = await resp.json(content_type=None)
                except Exception as e:
                    logger.warning("[GOG] Failed to fetch page %d: %s", page, e)
                    continue

                products = data.get("products", [])
                results.extend(self._parse_products(products))
                logger.info("[GOG] Page %d/%d: %d games total", page, total_pages, len(results))

        logger.info("[GOG] Fetched %d free games", len(results))
        return results

    @staticmethod
    def _parse_products(products: list) -> list[dict]:
        games = []
        for p in products:
            slug = p.get("slug", "")
            if not slug:
                continue
            gid = str(p.get("id", slug))
            name = p.get("title", slug)
            url = f"https://www.gog.com/en/game/{slug}"
            image_url: Optional[str] = p.get("coverHorizontal") or None

            # Description from genres + developers
            genres = [g["name"] for g in p.get("genres", []) if g.get("name")]
            devs = [d["name"] for d in p.get("developers", []) if d.get("name")]
            desc_parts = []
            if genres:
                desc_parts.append(", ".join(genres))
            if devs:
                desc_parts.append(", ".join(devs))
            description = " | ".join(desc_parts) if desc_parts else None

            games.append({
                "id": gid,
                "name": name,
                "url": url,
                "image_url": image_url,
                "description": description,
            })
        return games
