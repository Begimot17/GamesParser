"""Game info lookup service (price, genre, metacritic) for Steam, EGS, and GOG."""

import asyncio
import dataclasses
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import aiohttp


logger = logging.getLogger(__name__)

try:
    from src.common.logger import missing_data_logger
except ImportError:
    missing_data_logger = logging.getLogger("GamesParser.MissingData")

STEAM_API_URL = "https://store.steampowered.com/api/appdetails"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"
GOG_FREE_URL = "https://www.gog.com/games/ajax/filtered?mediaType=game&price=free&page=1"
TIMEOUT = aiohttp.ClientTimeout(total=8)

# Steam category IDs
_CONTROLLER_CATS = {18, 28}       # Partial / Full controller support
_MULTIPLAYER_CATS = {1, 9, 27, 36, 37}  # Multi-player, Co-op, Cross-Platform, Online PvP/Co-op

_LANG_RU_RE = re.compile(r'Русский|Russian', re.IGNORECASE)
_LANG_UA_RE = re.compile(r'Украин|Українськ|Ukrainian', re.IGNORECASE)
_AUDIO_RE = re.compile(r'<strong>\*</strong>')


@dataclass(slots=True)
class GameInfo:
    """Aggregated info about a game from a store page."""

    name: Optional[str] = None
    price: Optional[str] = None
    original_price: Optional[str] = None
    discount_pct: int = 0
    genre: Optional[str] = None
    metacritic: Optional[int] = None
    developer: Optional[str] = None
    is_free: bool = False
    review_score: Optional[str] = None
    short_description: Optional[str] = None
    header_image: Optional[str] = None
    # Extended Steam fields
    has_controller_support: bool = False
    has_multiplayer: bool = False
    has_russian_text: bool = False
    has_russian_audio: bool = False
    has_ukrainian_text: bool = False
    has_ukrainian_audio: bool = False
    recommendations_total: Optional[int] = None
    top_reviews: Optional[list] = None

    def __post_init__(self):
        if self.top_reviews is None:
            self.top_reviews = []

    def format_price(self) -> Optional[str]:
        """Returns HTML-formatted price string with discount markers."""
        if self.is_free:
            return "Бесплатно"
        if not self.price:
            return None
        if self.discount_pct and self.original_price:
            return f"<s>{self.original_price}</s> {self.price} (-{self.discount_pct}%)"
        return self.price

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GameInfo":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


class PriceService:
    """Fetches game info (price, genre, metacritic) from store APIs."""

    EGS_CACHE_TTL = timedelta(minutes=30)
    GOG_CACHE_TTL = timedelta(minutes=30)

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._egs_cache: Optional[list] = None
        self._egs_cache_ts: Optional[datetime] = None
        self._gog_cache: Optional[list] = None
        self._gog_cache_ts: Optional[datetime] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ── Steam ──────────────────────────────────────────────────────────────

    def _extract_steam_app_id(self, url: str) -> Optional[str]:
        m = re.search(r"/app/(\d+)", url)
        return m.group(1) if m else None

    async def get_steam_info(self, url: str, lang: str = "russian") -> Optional[GameInfo]:
        """Fetch price + genre + metacritic + languages + categories from Steam API.

        Args:
            url: Steam store URL containing /app/{id}.
            lang: Language for description/genre text (default 'russian'; use 'english' for estate alerts).
        """
        app_id = self._extract_steam_app_id(url)
        if not app_id:
            missing_data_logger.warning("[Steam] Cannot extract app_id from URL: %s", url)
            return None
        try:
            params = {"appids": app_id, "cc": "ua", "l": lang}
            session = await self._get_session()

            # Fetch appdetails and top reviews concurrently
            details_resp, reviews = await asyncio.gather(
                self._fetch_steam_details(session, params, app_id, url),
                self._get_steam_reviews(session, app_id),
                return_exceptions=True,
            )
            if isinstance(details_resp, Exception) or details_resp is None:
                return None
            info = details_resp

            is_free = bool(info.get("is_free"))
            price_raw = info.get("price_overview") or {}

            genres_list = info.get("genres") or []
            genre = ", ".join(g.get("description", "") for g in genres_list[:3]) or None

            mc = info.get("metacritic") or {}
            metacritic = mc.get("score") or None

            devs = info.get("developers") or []
            developer = devs[0] if devs else None

            game_name = info.get("name")
            review_score = info.get("review_score_desc") or None

            # Categories
            cat_ids = {c.get("id") for c in (info.get("categories") or [])}
            has_controller = bool(cat_ids & _CONTROLLER_CATS)
            has_mp = bool(cat_ids & _MULTIPLAYER_CATS)

            # Language support
            lang_html = info.get("supported_languages") or ""
            has_ru_text, has_ru_audio, has_ua_text, has_ua_audio = self._parse_languages(lang_html)

            # Recommendations count
            recs = (info.get("recommendations") or {}).get("total")

            top_reviews = reviews if isinstance(reviews, list) else []

            return GameInfo(
                name=game_name,
                price=price_raw.get("final_formatted") if price_raw else None,
                original_price=price_raw.get("initial_formatted") if price_raw else None,
                discount_pct=price_raw.get("discount_percent", 0) if price_raw else 0,
                genre=genre,
                metacritic=int(metacritic) if metacritic else None,
                developer=developer,
                is_free=is_free,
                review_score=review_score,
                short_description=info.get("short_description") or None,
                header_image=(
                    info.get("header_image")
                    or f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
                ),
                has_controller_support=has_controller,
                has_multiplayer=has_mp,
                has_russian_text=has_ru_text,
                has_russian_audio=has_ru_audio,
                has_ukrainian_text=has_ua_text,
                has_ukrainian_audio=has_ua_audio,
                recommendations_total=int(recs) if recs else None,
                top_reviews=top_reviews,
            )
        except Exception as e:
            logger.debug("Steam info lookup failed for %s: %s", url, e)
            return None

    async def _fetch_steam_details(self, session, params, app_id, url) -> Optional[dict]:
        """Fetch and validate Steam appdetails. Returns info dict or None."""
        async with session.get(STEAM_API_URL, params=params, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
        game = data.get(app_id, {})
        if not game.get("success"):
            missing_data_logger.warning("[Steam] success=False app_id=%s url=%s", app_id, url)
            return None
        return game.get("data", {})

    async def _get_steam_reviews(self, session, app_id: str, count: int = 2) -> list[str]:
        """Fetch top Russian reviews for a Steam app."""
        try:
            url = STEAM_REVIEWS_URL.format(app_id=app_id)
            params = {
                "json": 1, "filter": "top", "language": "russian",
                "num_per_page": count, "cursor": "*", "purchase_type": "all",
            }
            async with session.get(url, params=params, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
            return [
                r.get("review", "").strip()
                for r in (data.get("reviews") or [])
                if r.get("review", "").strip()
            ][:count]
        except Exception:
            return []

    @staticmethod
    def _parse_languages(lang_html: str) -> tuple[bool, bool, bool, bool]:
        """Parse Steam supported_languages HTML string.

        Returns (has_ru_text, has_ru_audio, has_ua_text, has_ua_audio).
        Audio is indicated by <strong>*</strong> after the language name.
        """
        def _check(pattern):
            m = pattern.search(lang_html)
            if not m:
                return False, False
            # Check if <strong>*</strong> appears right after the match
            tail = lang_html[m.end():m.end() + 40]
            has_audio = bool(_AUDIO_RE.search(tail))
            return True, has_audio

        has_ru, has_ru_audio = _check(_LANG_RU_RE)
        has_ua, has_ua_audio = _check(_LANG_UA_RE)
        return has_ru, has_ru_audio, has_ua, has_ua_audio

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
        """Fetch currently free EGS games list (TTL-cached per instance)."""
        now = datetime.utcnow()
        if (
            self._egs_cache is not None
            and self._egs_cache_ts is not None
            and (now - self._egs_cache_ts) < self.EGS_CACHE_TTL
        ):
            return self._egs_cache
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            session = await self._get_session()
            async with session.get(self.EGS_FREE_PROMO_URL, timeout=TIMEOUT, headers=headers) as resp:
                if resp.status != 200:
                    return self._egs_cache or []
                data = await resp.json(content_type=None)
            elements = (
                data.get("data", {})
                .get("Catalog", {})
                .get("searchStore", {})
                .get("elements", [])
            )
            self._egs_cache = elements
            self._egs_cache_ts = now
            return elements
        except Exception as e:
            logger.debug("EGS free games fetch failed: %s", e)
            return self._egs_cache or []

    async def get_egs_info(self, url: str) -> Optional[GameInfo]:
        """Fetch EGS game info from free promotions endpoint."""
        slug = self._extract_egs_slug(url)
        if not slug:
            missing_data_logger.warning("[EGS] Cannot extract slug from URL: %s", url)
            return None
        try:
            elements = await self._get_egs_free_games()
            for elem in elements:
                prod_slug = (elem.get("productSlug") or "").rstrip("/home").rstrip("/")
                url_slug = (elem.get("urlSlug") or "")
                if slug in (prod_slug, url_slug):
                    return self._parse_egs_element(elem)
            missing_data_logger.info("[EGS] Game not found in free promotions | slug=%s | url=%s", slug, url)
        except Exception as e:
            logger.debug("EGS info lookup failed for %s: %s", url, e)
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

    # ── GOG ────────────────────────────────────────────────────────────────

    def _extract_gog_slug(self, url: str) -> Optional[str]:
        m = re.search(r"/game/([^/?#]+)", url)
        return m.group(1) if m else None

    async def _get_gog_free_games(self) -> list:
        """Fetch currently free GOG games list (TTL-cached per instance)."""
        now = datetime.utcnow()
        if (
            self._gog_cache is not None
            and self._gog_cache_ts is not None
            and (now - self._gog_cache_ts) < self.GOG_CACHE_TTL
        ):
            return self._gog_cache
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            session = await self._get_session()
            async with session.get(GOG_FREE_URL, timeout=TIMEOUT, headers=headers) as resp:
                if resp.status != 200:
                    return self._gog_cache or []
                data = await resp.json(content_type=None)
            products = data.get("products", [])
            self._gog_cache = products
            self._gog_cache_ts = now
            return products
        except Exception as e:
            logger.debug("GOG free games fetch failed: %s", e)
            return self._gog_cache or []

    async def get_gog_info(self, url: str) -> Optional[GameInfo]:
        """Check if a GOG game is in the free promotions list."""
        slug = self._extract_gog_slug(url)
        if not slug:
            missing_data_logger.warning("[GOG] Cannot extract slug from URL: %s", url)
            return None
        try:
            products = await self._get_gog_free_games()
            for product in products:
                product_slug = product.get("slug", "")
                if product_slug == slug:
                    price_info = product.get("price", {})
                    is_free = str(price_info.get("amount", "1")) == "0"
                    genre_tags = product.get("genres", [])
                    genre = ", ".join(genre_tags[:3]) if genre_tags else None
                    developer = product.get("developer") or None
                    return GameInfo(
                        name=product.get("title"),
                        genre=genre,
                        developer=developer,
                        is_free=is_free,
                    )
            missing_data_logger.info("[GOG] Game not found in free promotions | slug=%s | url=%s", slug, url)
        except Exception as e:
            logger.debug("GOG info lookup failed for %s: %s", url, e)
        return None

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
            if store == "gog":
                return await self.get_gog_info(str(url))
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
