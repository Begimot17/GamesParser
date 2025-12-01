"""VGTimes parser for GamesParser project."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
from pydantic import ValidationError

from src.common.logger import logger
from src.config.config import Config
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser
from src.services.llm_g4f import LLMG4F
from src.storage.storage import JsonStorage


class VGTimesParser(BaseParser):
    """Парсер для получения постов с VGTimes."""

    REQUEST_TIMEOUT = Config.REQUEST_TIMEOUT
    MAX_TEXT_LENGTH = Config.MAX_TEXT_LENGTH
    VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    RATE_LIMIT_DELAY = 2
    TARGET_URLS = Config.VGTimes_URLS

    SELECTORS = {
        "articles": "ul.list-items > li",
        "title": "div.item-name.type0 a:first-child",
        "link": "div.item-name.type0 a:first-child",
        "image": "div.image_wrap.type0 img",
        "rating": "div.rrating div.text",
        "store_links": 'a.l_ks[target="_blank"]',
        "content": "div.article_text",
        "date": "div.date",
    }

    def __init__(self):
        super().__init__()
        self.storage = JsonStorage(Config.DB_PATH)
        self.llm = LLMG4F()

    async def fetch_posts(self, url: str = None) -> list[Post]:
        """Fetch and parse posts from VGTimes."""
        logger.info("[VGTimesParser] Starting fetch_posts...")
        all_posts = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            try:
                async with aiohttp.ClientSession() as session:
                    self.session = session
                    html = await self._fetch_page(target_url)
                    posts = await self._process_page(html)
                    all_posts.extend(posts)
            except Exception as e:
                logger.error(f"[VGTimesParser] Error fetching posts from {target_url}: {e}", exc_info=True)
        return all_posts

    async def stream_posts(self):
        """Генератор для потокового получения статей по мере их парсинга."""
        logger.info("[VGTimesParser] Starting stream_posts...")
        for target_url in self.TARGET_URLS:
            try:
                async with aiohttp.ClientSession() as session:
                    self.session = session
                    html = await self._fetch_page(target_url)
                    soup = BeautifulSoup(html, "html.parser")
                    articles = soup.select(self.SELECTORS["articles"])

                    for article_html in articles:
                        post = await self._parse_article(article_html)
                        if post and not self.storage.is_processed(post.id):
                            yield post
            except Exception as e:
                logger.error(f"[VGTimesParser] Error streaming posts from {target_url}: {e}", exc_info=True)

    async def _fetch_page(self, url: str) -> str:
        """Выполнение HTTP запроса."""
        async with self.session.get(url, timeout=self.REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            return await response.text()

    async def _process_page(self, html: str) -> list[Post]:
        """Обработка HTML страницы."""
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select(self.SELECTORS["articles"])
        posts = []
        for article_html in articles:
            post = await self._parse_article(article_html)
            if post and not self.storage.is_processed(post.id):
                posts.append(post)
        return posts

    async def _parse_article(self, article_html) -> Optional[Post]:
        """Парсинг одной статьи."""
        try:
            link_elem = article_html.select_one(self.SELECTORS["link"])
            if not link_elem:
                return None

            link = link_elem.get("href")
            if not link.startswith("https://"):
                link = f"https://vgtimes.ru{link}"

            article_id = self._extract_id(link)
            if not article_id:
                return None

            title_elem = article_html.select_one(self.SELECTORS["title"])
            title = title_elem.get_text(strip=True) if title_elem else ""

            image_elem = article_html.select_one(self.SELECTORS["image"])
            image_url = image_elem.get("data-src") if image_elem else None

            rating_elem = article_html.select_one(self.SELECTORS["rating"])
            rating = rating_elem.get_text(strip=True) if rating_elem else None

            date_elem = article_html.select_one(self.SELECTORS["date"])
            date = self._parse_date(date_elem.get_text(strip=True)) if date_elem else None

            content = ""  # Оставляем пустым, LLM заполнит

            page_text = await self._fetch_full_page_text(link)
            if page_text:
                llm_data = await self.llm.extract_article_info(page_text, link)
                if llm_data.get("title"):
                    title = llm_data["title"]
                if llm_data.get("content"):
                    content = llm_data["content"]

                store_links = llm_data.get("store_links", {})
                images = llm_data.get("images", [])
                if image_url and image_url not in images:
                    images.insert(0, image_url)
            else:
                store_links = self._extract_store_links(article_html)
                images = [image_url] if image_url else []

            metadata = PostMetadata(
                rating=rating,
                store_links=store_links,
                images=images,
                date=date,
            )

            return Post(
                id=article_id,
                title=title,
                link=link,
                content=content,
                metadata=metadata,
            )
        except ValidationError as e:
            logger.error(f"Validation error for article {link}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing article {link}: {e}", exc_info=True)
            return None

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date from string like '5 апреля 2025, 23:22'."""
        try:
            date_str = re.sub(r"<i.*?</i>", "", date_str).strip()
            ru_to_en = {
                "января": "January",
                "февраля": "February",
                "марта": "March",
                "апреля": "April",
                "мая": "May",
                "июня": "June",
                "июля": "July",
                "августа": "August",
                "сентября": "September",
                "октября": "October",
                "ноября": "November",
                "декабря": "December",
            }
            for ru, en in ru_to_en.items():
                date_str = date_str.replace(ru, en)

            dt = datetime.strptime(date_str, "%d %B %Y, %H:%M")
            return dt.replace(tzinfo=timezone(timedelta(hours=3)))
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}", exc_info=True)
            return None

    def _extract_store_links(self, article_html) -> dict:
        """Extract store links from article."""
        store_links = {}
        link_elements = article_html.select(self.SELECTORS["store_links"])
        for link in link_elements:
            href = link.get("href", "")
            if "store.steampowered.com" in href:
                store_links["Steam"] = href
            elif "epicgames.com" in href:
                store_links["Epic Games"] = href
            elif "gog.com" in href:
                store_links["GOG"] = href
        return store_links

    async def _fetch_full_page_text(self, post_link: str) -> str:
        """Fetch the full page text for LLM processing."""
        try:
            async with self.session.get(post_link) as response:
                if response.status != 200:
                    return ""
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    element.decompose()
                main_content = soup.select_one(".article_text")
                return main_content.get_text(" ", strip=True) if main_content else ""
        except Exception as e:
            logger.error(f"Error fetching page text from {post_link}: {e}", exc_info=True)
            return ""
