"""Game info lookup service (price, genre, metacritic) for Steam and EGS."""

import asyncio
import logging
import re
from typing import Optional

import aiohttp


logger = logging.getLogger(__name__)

STEAM_API_URL = "https://store.steampowered.com/api/appdetails"
TIMEOUT = aiohttp.ClientTimeout(total=8)


class GameInfo:
    """Aggregated info about a game from a store page."""

    __slots__ = ("name", "price", "original_price", "discount_pct", "genre", "metacritic", "developer", "is_free")

    def __init__(
        self,
        name: Optional[str] = None,
        price: Optional[str] = None,
        original_price: Optional[str] = None,
        discount_pct: int = 0,
        genre: Optional[str] = None,
        metacritic: Optional[int] = None,
        developer: Optional[str] = None,
        is_free: bool = False,
    ):
        self.name = name
        self.price = price
        self.original_price = original_price
        self.discount_pct = discount_pct
        self.genre = genre
        self.metacritic = metacritic
        self.developer = developer
        self.is_free = is_free

    def format_price(self) -> Optional[str]:
        """Returns HTML-formatted price string with discount markers."""
        if self.is_free:
            return "Безкоштовно"
        if not self.price:
            return None
        if self.discount_pct and self.original_price:
            return f"<s>{self.original_price}</s> {self.price} (-{self.discount_pct}%)"
        return self.price

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "discount_pct": self.discount_pct,
            "genre": self.genre,
            "metacritic": self.metacritic,
            "developer": self.developer,
            "is_free": self.is_free,
        }

    @staticmethod
    def from_dict(d: dict) -> "GameInfo":
        return GameInfo(**d)


class PriceService:
    """Fetches game info (price, genre, metacritic) from store APIs."""

    # ── Steam ──────────────────────────────────────────────────────────────

    def _extract_steam_app_id(self, url: str) -> Optional[str]:
        m = re.search(r"/app/(\d+)", url)
        return m.group(1) if m else None

    async def get_steam_info(self, url: str) -> Optional[GameInfo]:
        """Fetch price + genre + metacritic from Steam API (UAH, uk locale)."""
        app_id = self._extract_steam_app_id(url)
        if not app_id:
            return None
        try:
            params = {"appids": app_id, "cc": "ua", "l": "uk"}
            async with aiohttp.ClientSession() as session:
                async with session.get(STEAM_API_URL, params=params, timeout=TIMEOUT) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)

            game = data.get(app_id, {})
            if not game.get("success"):
                return None
            info = game.get("data", {})

            is_free = bool(info.get("is_free"))
            price_raw = info.get("price_overview") or {}

            genres_list = info.get("genres") or []
            genre = ", ".join(g.get("description", "") for g in genres_list[:3]) or None

            mc = info.get("metacritic") or {}
            metacritic = mc.get("score") or None

            devs = info.get("developers") or []
            developer = devs[0] if devs else None

            game_name = info.get("name")

            return GameInfo(
                name=game_name,
                price=price_raw.get("final_formatted") if price_raw else None,
                original_price=price_raw.get("initial_formatted") if price_raw else None,
                discount_pct=price_raw.get("discount_percent", 0) if price_raw else 0,
                genre=genre,
                metacritic=int(metacritic) if metacritic else None,
                developer=developer,
                is_free=is_free,
            )
        except Exception as e:
            logger.debug("Steam info lookup failed for %s: %s", url, e)
            return None

    # ── Epic Games Store ────────────────────────────────────────────────────

    def _extract_egs_slug(self, url: str) -> Optional[str]:
        m = re.search(r"/p/([^/?#]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/product/([^/?#]+)", url)
        return m.group(1) if m else None

    # EGS free games promotions endpoint (works without auth)
    EGS_FREE_PROMO_URL = (
        "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
        "?locale=uk-UA&country=UA&allowCountries=UA"
    )

    async def _get_egs_free_games(self) -> list:
        """Fetch currently free EGS games list (cached per instance call)."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession() as session:
                async with session.get(self.EGS_FREE_PROMO_URL, timeout=TIMEOUT, headers=headers) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
            return (
                data.get("data", {})
                .get("Catalog", {})
                .get("searchStore", {})
                .get("elements", [])
            )
        except Exception as e:
            logger.debug("EGS free games fetch failed: %s", e)
            return []

    async def get_egs_info(self, url: str) -> Optional[GameInfo]:
        """Fetch EGS game info.

        EGS store pages are protected by Cloudflare and can't be scraped directly.
        We check the free games promotions endpoint (works without auth) and match
        by product slug. If the game is found there, we return its price (often free).
        Otherwise we return a minimal GameInfo with no price.
        """
        slug = self._extract_egs_slug(url)
        if not slug:
            return None
        try:
            elements = await self._get_egs_free_games()
            for elem in elements:
                prod_slug = (elem.get("productSlug") or "").rstrip("/home").rstrip("/")
                url_slug = (elem.get("urlSlug") or "")
                if slug in (prod_slug, url_slug):
                    return self._parse_egs_element(elem)
        except Exception as e:
            logger.debug("EGS info lookup failed for %s: %s", url, e)
        # Game not found in free promotions – no price available
        return None

    def _parse_egs_element(self, elem: dict) -> GameInfo:
        """Parse a game element from the EGS free promotions response."""
        total = elem.get("price", {}).get("totalPrice", {})
        fmt = total.get("fmtPrice", {})
        disc_price = total.get("discountPrice", -1)
        orig_price = total.get("originalPrice", 0)

        orig_fmt = (fmt.get("originalPrice") or "").strip()
        disc_fmt = (fmt.get("discountPrice") or "").strip()

        is_free = disc_price == 0 and orig_price == 0

        discount_pct = 0
        if orig_price and disc_price and orig_price != disc_price:
            try:
                discount_pct = round((1 - disc_price / orig_price) * 100)
            except ZeroDivisionError:
                discount_pct = 0

        # Genre from tags
        tags = elem.get("tags") or []
        genre_tags = [
            t.get("name", "") for t in tags
            if t.get("groupName", "").lower() in ("genre",)
        ]
        genre = ", ".join(genre_tags[:3]) or None

        developer = elem.get("developerDisplayName") or None

        return GameInfo(
            price=disc_fmt if not is_free else None,
            original_price=orig_fmt if orig_fmt != disc_fmt and not is_free else None,
            discount_pct=discount_pct,
            genre=genre,
            metacritic=None,
            developer=developer,
            is_free=is_free,
        )

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_all_info(self, store_links: dict) -> dict:
        """Fetch game info for all store links concurrently.

        Returns a dict that mirrors store_links structure:
          {"steam": GameInfo(...)}                     — single game
          {"itch": [None, None], "steam": [GameInfo, GameInfo]}  — bundle
        """

        async def _fetch(store: str, url: str) -> Optional[GameInfo]:
            if store == "steam":
                return await self.get_steam_info(str(url))
            if store == "epicgames":
                return await self.get_egs_info(str(url))
            return None

        tasks = []
        index = []
        for store, val in store_links.items():
            urls = val if isinstance(val, list) else [val]
            for i, url in enumerate(urls):
                tasks.append(_fetch(store, url))
                index.append((store, i, len(urls)))

        raw = await asyncio.gather(*tasks, return_exceptions=True)

        result: dict = {}
        for (store, pos, total), info in zip(index, raw):
            if isinstance(info, Exception):
                info = None
            if total == 1:
                result[store] = info
            else:
                result.setdefault(store, [None] * total)
                if isinstance(result[store], list):
                    result[store][pos] = info

        return result


def _deep_find(obj, key: str):
    """Recursively find a key in a nested dict/list."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _deep_find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find(item, key)
            if found is not None:
                return found
    return None
