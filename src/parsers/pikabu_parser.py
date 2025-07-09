"""Pikabu parser for GamesParser project."""

import asyncio
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

from common import logger
from parsers.utils.base_parser import BaseParser
from src.config.config import Config
from src.models.models import Post, PostMetadata


class PikabuParser(BaseParser):
    """Парсер для получения постов из сообщества Steam на Pikabu."""

    REQUEST_TIMEOUT: int = Config.REQUEST_TIMEOUT
    MAX_TEXT_LENGTH: int = Config.MAX_TEXT_LENGTH
    VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    RATE_LIMIT_DELAY: int = 2
    TARGET_URL: str = "https://pikabu.ru/community/steam"
    SELECTORS = {
        "articles": "article[data-story-id]",
        "title": "h2.story__title a.story__title-link",
        "link": "a.story__title-link",
        "content": "div.story__content",
        "rating": "div.story__rating-count",
        "images": [
            "div.story-block_type_image img.story-image__image",
            "div.story__image img",
            "img.story__image",
            "div.story__content img",
            "div.story-block img",
            "img[src*='story-image']",
            "img[src*='story__image']",
            "img[src*='story-block']",
            "img[data-src]",
        ],
        "author": "a.story__user-link",
        "date": "time.story__datetime",
        "tags": "a.story__tag",
        "store_links": "a[href]",
    }

    async def __aenter__(self) -> "PikabuParser":
        """Вход в асинхронный контекстный менеджер."""
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Выход из асинхронного контекстного менеджера."""
        if self.session:
            await self.session.close()

    def _clean_store_url(self, url: str) -> str:
        """Очистка и проверка URL магазина."""
        if not url:
            return ""
        url = self._normalize_url(url)
        url = url.split("?")[0].split("#")[0]
        if "store.steampowered.com" in url and not re.search(r"/app/\d+/", url):
            return ""
        if "epicgames.com" in url and not re.search(r"/p/[^/]+$", url):
            return ""
        if "itch.io" in url and (url.rstrip("/").count("/") < 3 or url.endswith("/itch.io")):
            return ""
        if "gog.com" in url and not re.search(r"/game/[^/]+$", url):
            return ""
        if not any(
            store in url
            for store in [
                "store.steampowered.com",
                "epicgames.com",
                "itch.io",
                "gog.com",
            ]
        ):
            return ""
        return url

    def _extract_store_links(self, text: str) -> dict:
        """Извлечение ссылок на магазины из текста."""
        stores: dict = {}
        for store_name, pattern in self.store_patterns.items():
            store_links = re.findall(rf"\[{store_name}\]\((https?://[^)]+)\)", text, re.IGNORECASE)
            if store_links:
                cleaned_url = self._clean_store_url(store_links[0])
                if cleaned_url:
                    stores[store_name] = cleaned_url
                continue
            store_links = re.findall(rf'https?://[^"\s]+{pattern.pattern}[^"\s]*', text)
            if store_links:
                cleaned_url = self._clean_store_url(store_links[0])
                if cleaned_url and "/accounts/" not in cleaned_url:
                    stores[store_name] = cleaned_url
        return stores

    async def fetch_posts(self) -> list:
        """Получение и обработка постов."""
        logger.info("[PikabuParser] Starting fetch_posts...")
        try:
            await self._rate_limit()
            logger.info(f"[PikabuParser] Fetching page: {self.TARGET_URL}")
            response = await self._fetch_page(self.TARGET_URL)
            logger.info(f"[PikabuParser] Got response, length: {len(response)}")
            posts = self._process_page(response)
            logger.info(f"[PikabuParser] Parsed {len(posts)} posts from page")
            return posts
        except Exception as e:
            logger.error("[PikabuParser] Unexpected error in Pikabu parser: %s", str(e), exc_info=True)
            return []

    async def _fetch_page(self, url: str) -> str:
        """Выполнение HTTP запроса с повторными попытками."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession(headers=self.headers)
                async with self.session.get(url, timeout=self.REQUEST_TIMEOUT) as response:
                    response.raise_for_status()
                    return await response.text()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
                await asyncio.sleep(2**attempt)

    def _process_page(self, html: str) -> list:
        """Обработка HTML страницы."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            posts: list = []
            for article in soup.select(self.SELECTORS["articles"]):
                try:
                    post = self._parse_article(article)
                    if post:
                        posts.append(post)
                except Exception as e:
                    logger.error(f"Ошибка при парсинге статьи Pikabu: {e}", exc_info=True)
            return posts
        except Exception as e:
            logger.error(f"Ошибка при обработке страницы Pikabu: {e}", exc_info=True)
            return []

    def _clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов."""
        if not text:
            return ""
        text = text.strip()
        if len(text) > self.MAX_TEXT_LENGTH:
            return text[: self.MAX_TEXT_LENGTH] + "..."
        return text

    def _normalize_url(self, url: str, base_url: str = None) -> str:
        """Нормализация URL."""
        if not url:
            return ""
        try:
            if url.startswith("//"):
                url = f"https:{url}"
            elif url.startswith("/"):
                base_url = base_url or self.TARGET_URL
                url = urljoin(base_url, url)
            elif not urlparse(url).scheme:
                url = f"https://{url}"
            return url
        except Exception as e:
            logger.error(f"Ошибка при нормализации URL {url}: {e}")
            return ""

    def _parse_article(self, article: Tag) -> Optional[Post]:
        """Парсинг статьи с главной страницы Pikabu."""
        try:
            post_id = article.get("data-story-id")
            if not post_id:
                logger.warning("No post ID found in Pikabu article")
                return None
            title_element = article.select_one(self.SELECTORS["title"])
            if not title_element:
                logger.warning(f"No title found for Pikabu post {post_id}")
                return None
            title = self._clean_text(title_element.text)
            if not title:
                logger.warning(f"Empty title for Pikabu post {post_id}")
                return None
            link = self._normalize_url(title_element.get("href", ""))
            if not link:
                logger.warning(f"No link found for Pikabu post {post_id}")
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
                        logger.warning(f"Invalid date format for Pikabu post {post_id}: {date_str}")
            content_element = article.select_one(self.SELECTORS["content"])
            content = self._clean_text(content_element.text) if content_element else ""
            images: list = []
            for selector in self.SELECTORS["images"]:
                for img in article.select(selector):
                    src = img.get("src") or img.get("data-src")
                    if src:
                        src = self._normalize_url(src)
                        if src and any(src.endswith(ext) for ext in self.VALID_IMAGE_EXTENSIONS):
                            if "/avatars/" in src:
                                continue
                            images.append(src)
            store_links = self._extract_store_links(content)
            metadata = PostMetadata(rating=rating, store_links=store_links, images=images, date=date)
            return Post(
                id=post_id,
                title=title,
                link=link,
                content=content,
                date=date,
                metadata=metadata,
            )
        except Exception as e:
            logger.error(f"Ошибка при парсинге статьи Pikabu: {e}", exc_info=True)
            return None
