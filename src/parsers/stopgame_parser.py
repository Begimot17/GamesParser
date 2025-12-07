"""StopGame parser for GamesParser project."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, AsyncIterator, Dict, Any
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.common.logger import logger
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser
from src.services.llm_g4f import LLMG4F
from src.storage.sqlite_storage import SQLiteStorage


class StopGameParser(BaseParser):
    """Парсер для получения новостей с StopGame.ru."""

    def __init__(self):
        self.config = settings.PARSERS_CONFIG.get("stopgame", {})
        self.TARGET_URLS = self.config.get("target_urls", "").split(',') if isinstance(self.config.get("target_urls"), str) else self.config.get("target_urls", [])
        if not self.config:
            logger.warning("StopGame configuration not found in settings! Using defaults.")
            self.TARGET_URLS = ["https://stopgame.ru/news"]

        super().__init__(default_base_url=self.TARGET_URLS[0] if self.TARGET_URLS else None)

        self.REQUEST_TIMEOUT = self.config.get("request_timeout", settings.REQUEST_TIMEOUT)
        self.MAX_TEXT_LENGTH = self.config.get("max_text_length", settings.MAX_TEXT_LENGTH)
        self.VALID_IMAGE_EXTENSIONS = tuple(self.config.get("valid_image_extensions", [".jpg", ".jpeg", ".png", ".gif", ".webp"]))
        self.RATE_LIMIT_DELAY = self.config.get("rate_limit_delay", 2)
        self.SELECTORS = self.config.get("selectors", {})
        self.STORE_CONFIG = self.config.get("stores", {})

        self.storage = SQLiteStorage(settings.DB_PATH)
        self.llm = LLMG4F(model_name=settings.LLM_MODEL)

    async def _process_url(self, target_url: str) -> AsyncIterator[Post]:
        """Processes a single URL and yields posts."""
        html = ""
        try:
            await self._rate_limit()
            logger.info(f"[StopGameParser] Processing page: {target_url}")
            html = await self._fetch_page(target_url)
            logger.info(f"[StopGameParser] Got response, length: {len(html)}")

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info(f"[StopGameParser] Found {len(articles)} articles on page")

            for article in articles:
                try:
                    post = await self._parse_article(article, preloaded_html=html)
                    if post:
                        if await self.storage.is_processed(post.id):
                            logger.debug(f"[StopGameParser] Post {post.id} already processed, skipping")
                            continue
                            
                        logger.info(f"[StopGameParser] Yielding post {post.id}")
                        yield post
                except Exception as e:
                    logger.error(f"[StopGameParser] Error processing individual article: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[StopGameParser] Unexpected error in _process_url for {target_url}: {e}", exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    async def fetch_posts(self, url: str = None) -> list[Post]:
        """Fetch and parse posts from StopGame."""
        logger.info("[StopGameParser] Starting fetch_posts...")
        all_posts = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            async for post in self._process_url(target_url):
                all_posts.append(post)
        logger.info(f"[StopGameParser] fetch_posts completed. Total posts: {len(all_posts)}")
        return all_posts

    async def stream_posts(self) -> AsyncIterator[Post]:
        """Генератор для потокового получения статей по мере их парсинга."""
        logger.info("[StopGameParser] Starting stream_posts...")
        for target_url in self.TARGET_URLS:
            async for post in self._process_url(target_url):
                yield post
        logger.info("[StopGameParser] stream_posts completed")

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        match = re.search(r"(?:newsdata|show)/(\d+)", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date from string like '15 июля 2024 в 23:22', 'Вчера в 18:00'."""
        try:
            date_str = re.sub(r"<i.*?</i>", "", date_str).strip()
            
            # Normalize months
            ru_to_en = {
                "января": "January", "февраля": "February", "марта": "March",
                "апреля": "April", "мая": "May", "июня": "June", "июля": "July",
                "августа": "August", "сентября": "September", "октября": "October",
                "ноября": "November", "декабря": "December",
            }
            for ru, en in ru_to_en.items():
                date_str = date_str.replace(ru, en)

            # Handle relative dates
            now = datetime.now(timezone(timedelta(hours=3)))
            if "сегодня" in date_str.lower():
                date_part = now.strftime("%d %B %Y")
                time_match = re.search(r"(\d{1,2}:\d{2})", date_str)
                time_part = time_match.group(1) if time_match else "00:00"
                date_str = f"{date_part} {time_part}"
            elif "вчера" in date_str.lower():
                yesterday = now - timedelta(days=1)
                date_part = yesterday.strftime("%d %B %Y")
                time_match = re.search(r"(\d{1,2}:\d{2})", date_str)
                time_part = time_match.group(1) if time_match else "00:00"
                date_str = f"{date_part} {time_part}"
            
            # Try multiple formats
            formats = [
                "%d %B %Y в %H:%M",
                "%d %B %Y, %H:%M",
                "%d %B %Y %H:%M",
            ]
            
            dt = None
            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            
            if dt:
                return dt.replace(tzinfo=timezone(timedelta(hours=3)))
            
            logger.warning(f"Could not parse date string: {date_str}")
            return None
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}", exc_info=True)
            return None

    def _extract_store_links(self, article_html: Tag) -> dict:
        """Extract store links from article."""
        stores: dict = {}
        for link_tag in article_html.find_all('a', href=True):
            href = link_tag.get("href", "")
            for store_name, store_info in self.STORE_CONFIG.items():
                domain = store_info.get("domain")
                if domain and domain in href:
                    cleaned_url = self._clean_store_url(href, store_name)
                    if cleaned_url and store_name not in stores:
                        stores[store_name] = cleaned_url
                        break 
        return stores

    def _clean_store_url(self, url: str, store_name: str) -> str:
        """Очистка и проверка URL магазина."""
        if not url:
            return ""
        
        store_info = self.STORE_CONFIG.get(store_name, {})
        domain = store_info.get("domain")
        validation_regex = store_info.get("validation_regex")

        if not domain or domain not in url:
            return ""

        url = self._normalize_url(url)
        url = url.split("?")[0].split("#")[0]

        if validation_regex and not re.search(validation_regex, url):
            return ""
        
        return url

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
        image_url = image_elem.get("src") if image_elem else None
        
        date = None
        date_elem = article_html.select_one(self.SELECTORS["date"])
        if date_elem:
             date = self._parse_date(date_elem.get_text(strip=True))

        return {
            "id": article_id,
            "title": title,
            "link": link,
            "image_url": image_url,
            "date": date,
        }

    async def _parse_article(self, article_html: Tag, preloaded_html: Optional[str] = None) -> Optional[Post]:
        """Парсинг одной статьи."""
        initial_data = self._parse_initial_post_data(article_html)
        if not initial_data:
            return None

        post_id = initial_data["id"]
        try:
            title = initial_data["title"]
            content = ""  # Let LLM fill it
            images = [initial_data["image_url"]] if initial_data["image_url"] else []
            store_links = self._extract_store_links(article_html)

            # Use LLM to enrich post data only if enabled
            if settings.ENABLE_LLM:
                title, content, images, store_links = await self._update_post_with_llm_data(
                    title, content, images, initial_data["link"], store_links, preloaded_html
                )

            metadata = PostMetadata(
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
