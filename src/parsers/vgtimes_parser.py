"""VGTimes parser for GamesParser project."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, AsyncIterator, Dict, Any
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.common.logger import logger
from src.config.config import Config
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser
from src.services.llm_g4f import LLMG4F
from src.storage.storage import JsonStorage


class VGTimesParser(BaseParser):
    """Парсер для получения постов с VGTimes."""

    def __init__(self):
        super().__init__()
        parser_config = Config.PARSERS_CONFIG.get("vgtimes", {})

        self.REQUEST_TIMEOUT: int = parser_config.get("request_timeout", Config.REQUEST_TIMEOUT)
        self.MAX_TEXT_LENGTH: int = parser_config.get("max_text_length", Config.MAX_TEXT_LENGTH)
        self.VALID_IMAGE_EXTENSIONS = tuple(parser_config.get("valid_image_extensions", []))
        self.RATE_LIMIT_DELAY: int = parser_config.get("rate_limit_delay", 2)
        self.TARGET_URLS = parser_config.get("target_urls", "").split(',')
        self.SELECTORS = parser_config.get("selectors", {})
        self.STORE_CONFIG = parser_config.get("stores", {})

        self.storage = JsonStorage(Config.DB_PATH)
        self.llm = LLMG4F()

    async def __aenter__(self) -> "VGTimesParser":
        """Вход в асинхронный контекстный менеджер."""
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Выход из асинхронного контекстного менеджера."""
        if self.session:
            await self.session.close()

    async def _process_url(self, target_url: str) -> AsyncIterator[Post]:
        """Processes a single URL and yields posts."""
        html = ""
        try:
            await self._rate_limit()
            logger.info(f"[VGTimesParser] Processing page: {target_url}")
            html = await self._fetch_page(target_url)
            logger.info(f"[VGTimesParser] Got response, length: {len(html)}")

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info(f"[VGTimesParser] Found {len(articles)} articles on page")

            for article in articles:
                try:
                    post = await self._parse_article(article, preloaded_html=html) # Pass full HTML here
                    if post and not self.storage.is_processed(post.id):
                        logger.info(f"[VGTimesParser] Yielding post {post.id}")
                        yield post
                except Exception as e:
                    logger.error(f"[VGTimesParser] Error processing individual article: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[VGTimesParser] Unexpected error in _process_url for {target_url}: {e}", exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    async def fetch_posts(self, url: str = None) -> list[Post]:
        """Fetch and parse posts from VGTimes."""
        logger.info("[VGTimesParser] Starting fetch_posts...")
        all_posts = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            async for post in self._process_url(target_url):
                all_posts.append(post)
        logger.info(f"[VGTimesParser] fetch_posts completed. Total posts: {len(all_posts)}")
        return all_posts

    async def stream_posts(self) -> AsyncIterator[Post]:
        """Генератор для потокового получения статей по мере их парсинга."""
        logger.info("[VGTimesParser] Starting stream_posts...")
        for target_url in self.TARGET_URLS:
            async for post in self._process_url(target_url):
                yield post
        logger.info("[VGTimesParser] stream_posts completed")

    async def _fetch_page(self, url: str) -> str:
        """Выполнение HTTP запроса с повторными попытками."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.session or self.session.closed:
                    self.session = aiohttp.ClientSession(headers=self.headers)
                async with self.session.get(url, timeout=self.REQUEST_TIMEOUT) as response:
                    response.raise_for_status()
                    return await response.text()
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}", exc_info=True)
                    raise
                logger.warning(f"Attempt {attempt + 1} to fetch {url} failed: {e}. Retrying...")
                await asyncio.sleep(2**attempt)
        return ""

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date from string like '5 апреля 2025, 23:22'."""
        try:
            date_str = re.sub(r"<i.*?</i>", "", date_str).strip()
            ru_to_en = {
                "января": "January", "февраля": "February", "марта": "March",
                "апреля": "April", "мая": "May", "июня": "June", "июля": "July",
                "августа": "August", "сентября": "September", "октября": "October",
                "ноября": "November", "декабря": "December",
            }
            for ru, en in ru_to_en.items():
                date_str = date_str.replace(ru, en)

            dt = datetime.strptime(date_str, "%d %B %Y, %H:%M")
            return dt.replace(tzinfo=timezone(timedelta(hours=3)))
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}", exc_info=True)
            return None

    def _clean_store_url(self, url: str, store_name: str) -> str:
        """Очистка и проверка URL магазина."""
        if not url:
            return ""
        
        store_info = self.STORE_CONFIG.get(store_name, {})
        domain = store_info.get("domain")
        validation_regex = store_info.get("validation_regex")

        if not domain or domain not in url:
            return ""

        url = self._normalize_url(url, base_url=self.TARGET_URLS[0]) # Pass base_url
        url = url.split("?")[0].split("#")[0]

        if validation_regex and not re.search(validation_regex, url):
            return ""
        
        return url

    def _extract_store_links(self, article_html: Tag) -> dict:
        """Extract store links from article."""
        stores: dict = {} # Initialize stores here
        link_elements = article_html.select(self.SELECTORS["store_links"])
        for link in link_elements:
            href = link.get("href", "")
            for store_name, store_info in self.STORE_CONFIG.items():
                if store_info.get("domain") in href:
                    cleaned_url = self._clean_store_url(href, store_name)
                    if cleaned_url:
                        stores[store_name] = cleaned_url
                        break
        return stores

    async def _update_post_with_llm_data(self, title: str, content: str, images: list, link: str, store_links: dict, preloaded_html: Optional[str] = None) -> tuple[str, str, list, dict]:
        """Updates post data with information extracted by LLM."""
        page_text = await self._fetch_full_page_text(link, preloaded_html=preloaded_html)
        if page_text:
            llm_data = await self.llm.extract_article_info(page_text, link)

            if llm_data.get("title"):
                title = llm_data["title"]
            if llm_data.get("content"):
                content = llm_data["content"]
            if llm_data.get("store_links"):
                store_links = {k: v for k, v in llm_data["store_links"].items() if v and v.strip()}
            if llm_data.get("images"):
                images.extend(llm_data["images"])
        
        return title, content, images, store_links

    def _parse_initial_post_data(self, article_html: Tag) -> Optional[Dict[str, Any]]:
        """Parses the initial post data from the article tag."""
        link_elem = article_html.select_one(self.SELECTORS["link"])
        if not link_elem:
            return None

        link = link_elem.get("href")
        if not link.startswith("https://"):
            link = urljoin(self.TARGET_URLS[0], link)

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

        return {
            "id": article_id,
            "title": title,
            "link": link,
            "image_url": image_url,
            "rating": rating,
            "date": date,
        }

    async def _parse_article(self, article_html: Tag, preloaded_html: Optional[str] = None) -> Optional[Post]:
        """Парсинг одной статьи."""
        initial_data = self._parse_initial_post_data(article_html)
        if not initial_data:
            return None

        post_id = initial_data["id"]
        try:
            content = ""  # Оставляем пустым, LLM заполнит
            images = [initial_data["image_url"]] if initial_data["image_url"] else []
            store_links = self._extract_store_links(article_html)

            title, content, images, store_links = await self._update_post_with_llm_data(
                initial_data["title"], content, images, initial_data["link"], store_links, preloaded_html
            )

            metadata = PostMetadata(
                rating=initial_data["rating"],
                store_links=store_links,
                images=list(set(images)),
                date=initial_data["date"],
            )

            return Post(
                id=post_id,
                title=title,
                link=initial_data["link"],
                content=content,
                metadata=metadata,
            )
        except ValidationError as e:
            logger.error(f"Validation error for article {initial_data.get('link')}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing article {initial_data.get('link')}: {e}", exc_info=True)
            return None

    async def _fetch_full_page_text(self, post_link: str, preloaded_html: Optional[str] = None) -> str:
        """Fetch the full page text for LLM processing."""
        try:
            if preloaded_html:
                html = preloaded_html
            else:
                html = await self._fetch_page(post_link)
            
            if not html:
                return ""
            soup = BeautifulSoup(html, "html.parser")
            for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
                element.decompose()
            main_content = soup.select_one(self.SELECTORS["content"])
            return main_content.get_text(" ", strip=True) if main_content else ""
        except Exception as e:
            logger.error(f"Error fetching page text from {post_link}: {e}", exc_info=True)
            return ""
