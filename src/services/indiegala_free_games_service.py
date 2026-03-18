"""IndieGala free games scraper service."""

import asyncio
import re
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

from src.common.logger import logger

INDIEGALA_FREEBIES_URL = "https://freebies.indiegala.com/"


class IndieGalaFreeGamesService:
    """Scrapes free games from IndieGala freebies page.

    Uses cloudscraper to bypass Cloudflare protection.
    """

    PLATFORM = "indiegala"

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

    def _fetch_sync(self) -> str:
        session = self._get_session()
        resp = session.get(INDIEGALA_FREEBIES_URL, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"IndieGala freebies returned HTTP {resp.status_code}")
        return resp.text

    async def fetch_free_games(self) -> list[dict]:
        """Return list of free games: {id, name, url, image_url, description}."""
        try:
            html = await asyncio.to_thread(self._fetch_sync)
        except Exception as e:
            logger.error("[IndieGala] Failed to fetch freebies page: %s", e)
            return []

        games = self._parse_html(html)
        logger.info("[IndieGala] Fetched %d free games", len(games))
        return games

    @staticmethod
    def _parse_html(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        games = []

        # IndieGala freebies page uses game tiles/cards
        # Try multiple selectors to be resilient to layout changes
        tiles = (
            soup.select(".main-list-item")
            or soup.select(".giveaway-item")
            or soup.select("article.item")
            or soup.select(".showcase-item")
            or soup.select("[data-game-url]")
        )

        if not tiles:
            # Fallback: find all links pointing to /game/ paths
            links = soup.find_all("a", href=re.compile(r"/game/[\w-]+"))
            seen_slugs: set[str] = set()
            for link in links:
                href = link.get("href", "")
                m = re.search(r"/game/([\w-]+)", href)
                if not m:
                    continue
                slug = m.group(1)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                url = href if href.startswith("http") else f"https://freebies.indiegala.com{href}"
                name = link.get_text(strip=True) or slug
                img_tag = link.find("img")
                image_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else None

                games.append({
                    "id": slug,
                    "name": name,
                    "url": url,
                    "image_url": image_url,
                    "description": None,
                })
            return games

        for tile in tiles:
            # Try to get link and slug
            link_tag = tile.find("a", href=re.compile(r"/game/[\w-]+")) or tile.find("a")
            if not link_tag:
                continue

            href = link_tag.get("href", "")
            m = re.search(r"/game/([\w-]+)", href)
            slug = m.group(1) if m else re.sub(r"[^\w-]", "-", href.strip("/").split("/")[-1])
            if not slug:
                continue

            url = href if href.startswith("http") else f"https://freebies.indiegala.com{href}"

            # Game name
            name_tag = tile.select_one(".game-title, .title, h2, h3, .name")
            name = name_tag.get_text(strip=True) if name_tag else link_tag.get_text(strip=True) or slug

            # Image
            img_tag = tile.find("img")
            image_url: Optional[str] = None
            if img_tag:
                image_url = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-lazy-src")

            games.append({
                "id": slug,
                "name": name,
                "url": url,
                "image_url": image_url,
                "description": None,
            })

        return games
