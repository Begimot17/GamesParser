"""Pikabu parser for GamesParser project."""

import re
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.common.logger import logger, missing_data_logger
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser


class PikabuParser(BaseParser):
    """Парсер для получения постов из сообщества Steam на Pikabu."""

    def __init__(self):
        super().__init__(config_key="pikabu", default_url="https://pikabu.ru/community/steam")

    # ── Pagination ────────────────────────────────────────────────────────

    def _build_page_urls(self, pages: int) -> list[str]:
        """Page 1 = base URL, page N = /hot/N."""
        base = self.TARGET_URLS[0]
        urls = [base]
        for i in range(2, pages + 1):
            urls.append(f"{base}/hot/{i}")
        return urls

    # ── URL processing (pass preloaded_html for optional LLM reuse) ───────

    async def _process_url(self, target_url: str) -> AsyncGenerator:
        html = ""
        try:
            await self._rate_limit()
            logger.info("[PikabuParser] Processing page: %s", target_url)
            html = await self._fetch_page(target_url)
            logger.info("[PikabuParser] Got response, length: %d", len(html))

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info("[PikabuParser] Found %d articles on page", len(articles))

            for article in articles:
                try:
                    post = await self._parse_article(article, preloaded_html=html)
                    if post:
                        logger.info("[PikabuParser] Yielding post %s", post.id)
                        yield post
                except Exception as e:
                    logger.error("[PikabuParser] Error processing article: %s", e, exc_info=True)
        except Exception as e:
            logger.error("[PikabuParser] Unexpected error in _process_url for %s: %s", target_url, e, exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    # ── Store link extraction ─────────────────────────────────────────────

    def _extract_store_links(self, text: str) -> dict:
        """Extract store links from plain text via regex."""
        stores: dict = {}
        for store_name, store_info in self.STORE_CONFIG.items():
            domain = store_info.get("domain")
            if not domain:
                continue
            escaped = domain.replace(".", r"\.")
            pattern = rf"https?://(?:[\w-]+\.)*{escaped}[^\"'\s,\]\)]*"
            for url in re.findall(pattern, text, re.IGNORECASE):
                cleaned = self._clean_store_url(url, store_name)
                if cleaned:
                    stores[store_name] = cleaned
                    break
        return stores

    def _extract_store_links_from_html(self, article: Tag) -> dict:
        """Extract store links from HTML, decoding Pikabu redirect URLs (?u=...)."""
        buckets: dict = {}
        seen: set = set()
        for a in article.find_all("a", href=True):
            href = a.get("href", "")
            if "?u=" in href or "&u=" in href:
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                u_param = params.get("u", [None])[0]
                if u_param:
                    href = unquote(u_param)
            for store_name, store_info in self.STORE_CONFIG.items():
                domain = store_info.get("domain")
                if domain and domain in href:
                    cleaned = self._clean_store_url(href, store_name)
                    if cleaned and cleaned not in seen:
                        seen.add(cleaned)
                        buckets.setdefault(store_name, []).append(cleaned)
                    break
        return buckets

    # ── Article parsing ───────────────────────────────────────────────────

    def _clean_text(self, text: str) -> str:
        text = super()._clean_text(text)
        if len(text) > self.MAX_TEXT_LENGTH:
            return text[:self.MAX_TEXT_LENGTH] + "..."
        return text

    def _parse_tags(self, article: Tag) -> list:
        selector = self.SELECTORS.get("tags")
        if not selector:
            return []
        return [self._clean_text(t.get_text(strip=True)) for t in article.select(selector)]

    def _parse_stats(self, article: Tag) -> Optional[str]:
        selector = self.SELECTORS.get("stats")
        if not selector:
            return None
        elem = article.select_one(selector)
        return self._clean_text(elem.get_text(strip=True)) if elem else None

    def _parse_initial_post_data(self, article: Tag) -> Optional[Dict[str, Any]]:
        post_id = article.get("data-story-id")
        if not post_id:
            logger.warning("No post ID found in Pikabu article")
            return None

        title_element = article.select_one(self.SELECTORS["title"])
        if not title_element:
            logger.warning("No title found for Pikabu post %s", post_id)
            return None
        title = self._clean_text(title_element.text)
        if not title:
            logger.warning("Empty title for Pikabu post %s", post_id)
            return None

        link = self._normalize_url(title_element.get("href", ""))
        if not link:
            logger.warning("No link found for Pikabu post %s", post_id)
            return None

        rating_element = article.select_one(self.SELECTORS["rating"])
        rating = self._clean_text(rating_element.text) if rating_element else "0"

        date = None
        date_element = article.select_one(self.SELECTORS["date"])
        if date_element:
            date_str = date_element.get("datetime")
            if date_str:
                try:
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning("Invalid date format for Pikabu post %s: %s", post_id, date_str)

        content_element = article.select_one(self.SELECTORS["content"])
        content = self._clean_text(content_element.text) if content_element else ""

        images: list = []
        for selector in self.SELECTORS.get("images", []):
            for img in article.select(selector):
                src = img.get("src") or img.get("data-src")
                if src:
                    src = self._normalize_url(src)
                    if src and src.endswith(self.VALID_IMAGE_EXTENSIONS) and "/avatars/" not in src:
                        images.append(src)

        return {
            "id": post_id,
            "title": title,
            "link": link,
            "rating": rating,
            "date": date,
            "content": content,
            "images": images,
            "tags": self._parse_tags(article),
            "views": self._parse_stats(article),
        }

    async def _parse_article(self, article: Tag, preloaded_html: Optional[str] = None, **kwargs) -> Optional[Post]:
        initial_data = self._parse_initial_post_data(article)
        if not initial_data:
            return None

        post_id = initial_data["id"]
        if await self._already_known(post_id):
            logger.debug("[PikabuParser] Post %s already processed, skipping", post_id)
            return None
        try:
            title = initial_data["title"]
            content = initial_data["content"]
            images = initial_data["images"]

            store_links = self._extract_store_links_from_html(article)
            if not store_links:
                store_links = self._extract_store_links(content)

            if not store_links:
                missing_data_logger.warning(
                    "[Pikabu] No store links found | post_id=%s | title=%s | url=%s",
                    post_id, title, initial_data["link"],
                )
            elif "steam" not in store_links:
                missing_data_logger.warning(
                    "[Pikabu] No Steam link | post_id=%s | title=%s | stores=%s | url=%s",
                    post_id, title, list(store_links.keys()), initial_data["link"],
                )

            if not images:
                missing_data_logger.warning("[Pikabu] No image | post_id=%s | url=%s", post_id, initial_data["link"])

            if len(content) < 50:
                missing_data_logger.warning(
                    "[Pikabu] Content too short (%d chars) | post_id=%s | url=%s",
                    len(content), post_id, initial_data["link"],
                )

            if settings.ENABLE_LLM and self.llm:
                title, content, images, store_links = await self._update_post_with_llm_data(
                    title, content, images, initial_data["link"], store_links, preloaded_html,
                )
                if not store_links:
                    store_links = self._extract_store_links(content)

            game_info_raw = await self._build_game_info_raw(store_links)

            metadata = PostMetadata(
                rating=initial_data["rating"],
                store_links=store_links,
                images=list(set(images)),
                date=initial_data["date"],
                tags=initial_data["tags"],
                views=initial_data["views"],
                game_info=game_info_raw,
            )
            return Post(
                id=post_id,
                title=title,
                link=initial_data["link"],
                content=content,
                metadata=metadata,
                source="Pikabu",
            )
        except ValidationError as e:
            logger.error("Validation error for Pikabu post %s: %s", post_id, e)
            return None
        except Exception as e:
            logger.error("Error parsing Pikabu article %s: %s", post_id, e, exc_info=True)
            return None
