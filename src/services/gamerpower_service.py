"""GamerPower.com free games & giveaways API service.

Aggregates giveaways from Epic, GOG, Steam, Ubisoft, EA/Origin, Indiegala, and more.
Public API — no auth required.
"""

import re
from typing import Optional

import aiohttp

from src.common.logger import logger

GAMERPOWER_API_URL = "https://www.gamerpower.com/api/giveaways"

# Map GamerPower platform strings to our internal platform IDs
_PLATFORM_MAP = {
    "Epic Games Store": "egs",
    "Steam":            "steam",
    "GOG":              "gog",
    "Ubisoft":          "ubisoft",
    "Origin":           "ea",
    "EA":               "ea",
    "Indiegala":        "indiegala",
    "Fanatical":        "fanatical",
    "itch.io":          "itch",
    "Amazon":           "amazon",
    "Humble Bundle":    "humble",
}


class GamerPowerService:
    """Fetches active game giveaways from GamerPower.com API.

    Returns giveaways across many platforms in a single request.
    Each item has a platform tag derived from the GamerPower platforms field.
    """

    PLATFORM = "gamerpower"

    async def fetch_free_games(self) -> list[dict]:
        """Return list of active giveaways: {id, name, url, image_url, description, platform}."""
        params = {"type": "game", "status": "active"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    GAMERPOWER_API_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "Mozilla/5.0 GamesParserBot/1.0"},
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"GamerPower API returned HTTP {resp.status}")
                    data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("[GamerPower] Failed to fetch giveaways: %s", e)
            return []

        if not isinstance(data, list):
            logger.warning("[GamerPower] Unexpected response format: %s", type(data))
            return []

        games = [self._parse_item(item) for item in data if isinstance(item, dict)]
        games = [g for g in games if g is not None]
        logger.info("[GamerPower] Fetched %d active giveaways", len(games))
        return games

    @staticmethod
    def _parse_item(item: dict) -> Optional[dict]:
        gid = str(item.get("id", ""))
        if not gid:
            return None

        name = item.get("title", "").strip()
        if not name:
            return None

        # Prefer the direct open_giveaway_url (lands on the store page)
        url = item.get("open_giveaway_url") or item.get("gamerpower_url") or ""
        if not url:
            return None

        image_url: Optional[str] = item.get("image") or item.get("thumbnail") or None
        description: Optional[str] = item.get("description") or None
        if description:
            description = description.strip()

        # Determine platform from GamerPower's platforms string (e.g. "PC, Epic Games Store")
        platforms_raw: str = item.get("platforms", "") or ""
        platform = _resolve_platform(platforms_raw)

        worth: str = item.get("worth", "") or ""
        if worth in ("N/A", "$0.00"):
            worth = ""

        return {
            "id": gid,
            "name": _clean_title(name),
            "url": url,
            "image_url": image_url,
            "description": description,
            "platform": platform,
            "platforms": platforms_raw,
            "worth": worth or None,
        }


def _clean_title(title: str) -> str:
    """'Breathedge (Epic Games) Giveaway' → 'Breathedge'; '(Mobile)' is kept in `platforms` instead."""
    cleaned = re.sub(r"\s*\([^)]*\)\s*(?=Giveaway\s*$)", " ", title)
    cleaned = re.sub(r"\s+(?:Key\s+)?Giveaway\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or title


def _resolve_platform(platforms_raw: str) -> str:
    """Map GamerPower platforms string to our internal platform id."""
    for key, pid in _PLATFORM_MAP.items():
        if key.lower() in platforms_raw.lower():
            return pid
    # Generic fallback — still useful so we don't lose the giveaway
    return "gamerpower"
