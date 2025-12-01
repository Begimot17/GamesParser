"""Pikabu parser for GamesParser project."""

import asyncio
import re
from datetime import datetime
from typing import Optional, AsyncIterator, Tuple, Dict, Any
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.common.logger import logger
from src.config.config import Config
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser
from src.services.llm_g4f import LLMG4F
from src.storage.storage import JsonStorage


class PikabuParser(BaseParser):
    """Парсер для получения постов из сообщества Steam на Pikabu."""

    def __init__(self):
        parser_config = Config.PARSERS_CONFIG.get("pikabu", {})
        self.TARGET_URLS = parser_config.get("target_urls", "").split(',')
        super().__init__(default_base_url=self.TARGET_URLS[0])
        
        self.REQUEST_TIMEOUT: int = parser_config.get("request_timeout", Config.REQUEST_TIMEOUT)
        self.MAX_TEXT_LENGTH: int = parser_config.get("max_text_length", Config.MAX_TEXT_LENGTH)
        self.VALID_IMAGE_EXTENSIONS = tuple(parser_config.get("valid_image_extensions", []))
        self.RATE_LIMIT_DELAY: int = parser_config.get("rate_limit_delay", 2)
        self.SELECTORS = parser_config.get("selectors", {})
        self.STORE_CONFIG = parser_config.get("stores", {})

        self.llm = LLMG4F()
        self.storage = JsonStorage(Config.DB_PATH)

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
        
        # Special case for itch.io
        if store_name == "itch" and (url.rstrip("/").count("/") < 3 or url.endswith("/itch.io")):
            return ""

        return url

    def _extract_store_links(self, text: str) -> dict:
        """Извлечение ссылок на магазины из текста."""
        stores: dict = {}
        for store_name, store_info in self.STORE_CONFIG.items():
            domain = store_info.get("domain")
            if not domain:
                continue
            
            # Find all potential links for this domain
            escaped_domain = domain.replace('.', r'\.')
            pattern = rf"https?://(?:www\.)?{escaped_domain}[^\"'\s,\]\)]*"
            found_urls = re.findall(pattern, text, re.IGNORECASE)
            
            for url in found_urls:
                cleaned_url = self._clean_store_url(url, store_name)
                if cleaned_url:
                    stores[store_name] = cleaned_url
                    break # Found a valid link for this store, move to the next
        return stores

    async def _process_url(self, target_url: str) -> AsyncIterator[Post]:
        """Processes a single URL and yields posts."""
        html = ""
        try:
            await self._rate_limit()
            logger.info(f"[PikabuParser] Processing page: {target_url}")
            html = await self._fetch_page(target_url)
            logger.info(f"[PikabuParser] Got response, length: {len(html)}")

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info(f"[PikabuParser] Found {len(articles)} articles on page")

            for article in articles:
                try:
                    post_id = article.get("data-story-id")
                    if not post_id:
                        continue

                    if self.storage.is_processed(post_id):
                        logger.info(f"[PikabuParser] Post {post_id} already processed, skipping")
                        continue

                    post = await self._parse_article(article, preloaded_html=html) # Pass full HTML here
                    if post:
                        logger.info(f"[PikabuParser] Yielding post {post.id}")
                        yield post
                except Exception as e:
                    logger.error(f"[PikabuParser] Error processing individual article: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[PikabuParser] Unexpected error in _process_url for {target_url}: {e}", exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    async def fetch_posts(self) -> list[Post]:
        """Получение и обработка постов."""
        logger.info("[PikabuParser] Starting fetch_posts...")
        all_posts = []
        for target_url in self.TARGET_URLS:
            async for post in self._process_url(target_url):
                all_posts.append(post)
        logger.info(f"[PikabuParser] fetch_posts completed. Total posts: {len(all_posts)}")
        return all_posts

    async def stream_posts(self) -> AsyncIterator[Post]:
        """Генератор для потокового получения постов по мере их парсинга."""
        logger.info("[PikabuParser] Starting stream_posts...")
        for target_url in self.TARGET_URLS:
            async for post in self._process_url(target_url):
                yield post
        logger.info("[PikabuParser] stream_posts completed")

    def _clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов."""
        text = super()._clean_text(text)  # Call base class's clean_text first
        if len(text) > self.MAX_TEXT_LENGTH:
            return text[: self.MAX_TEXT_LENGTH] + "..."
        return text

    async def _update_post_with_llm_data(self, title: str, content: str, images: list, link: str, store_links: dict, preloaded_html: Optional[str] = None) -> tuple[str, str, list, dict]:
        """Updates post data with information extracted by LLM."""
        page_text = await self._fetch_full_page_text(link, preloaded_html=preloaded_html)
        if page_text:
            llm_data = await self.llm.extract_article_info(page_text, link)
            logger.info(f"[PikabuParser] LLM extracted data for {link}: {llm_data}")

            if llm_data.get("title"):
                title = llm_data["title"]
            if llm_data.get("content"):
                content = llm_data["content"]
            if llm_data.get("store_links"):
                store_links = {k: v for k, v in llm_data["store_links"].items() if v and v.strip()}
            if llm_data.get("images"):
                images.extend(llm_data["images"])
        
        if not store_links:
            store_links = self._extract_store_links(content)
            
        return title, content, images, store_links

    def _parse_initial_post_data(self, article: Tag) -> Optional[Dict[str, Any]]:
        """Parses the initial post data from the article tag."""
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
        for selector in self.SELECTORS.get("images", []):
            for img in article.select(selector):
                src = img.get("src") or img.get("data-src")
                if src:
                    src = self._normalize_url(src)
                    if src and src.endswith(self.VALID_IMAGE_EXTENSIONS):
                        if "/avatars/" in src:
                            continue
                        images.append(src)
        
        logger.info(f"[PikabuParser] Initial data for post {post_id}: content_len={len(content)}, images_count={len(images)}")

        return {
            "id": post_id,
            "title": title,
            "link": link,
            "rating": rating,
            "date": date,
            "content": content,
            "images": images,
        }

    async def _parse_article(self, article: Tag, preloaded_html: Optional[str] = None) -> Optional[Post]:
        """Парсинг статьи с главной страницы Pikabu."""
        initial_data = self._parse_initial_post_data(article)
        if not initial_data:
            return None

        post_id = initial_data["id"]
        try:
            # Update with LLM extracted data
            title, content, images, store_links = await self._update_post_with_llm_data(
                initial_data["title"], initial_data["content"], initial_data["images"], initial_data["link"], {}, preloaded_html
            )

            metadata = PostMetadata(rating=initial_data["rating"], store_links=store_links, images=list(set(images)), date=initial_data["date"])
            return Post(
                id=post_id,
                title=title,
                link=initial_data["link"],
                content=content,
                metadata=metadata,
            )
        except ValidationError as e:
            logger.error(f"Validation error for post {post_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при парсинге статьи Pikabu {post_id}: {e}", exc_info=True)
            return None

    async def _fetch_full_page_text(self, post_link: str, preloaded_html: Optional[str] = None) -> str:
        """Fetch the full page text for LLM processing."""
        try:
            logger.info(f"Fetching full page text from {post_link}")

            if preloaded_html:
                html = preloaded_html
            else:
                html = await self._fetch_page(post_link)
            
            if not html:
                logger.warning(f"No HTML fetched for {post_link}")
                return ""

            soup = BeautifulSoup(html, "html.parser")

            # Remove script and style elements
            for element in soup(["script", "style", "nav", "header", "footer", "aside", ".sidebar"]):
                element.decompose()

            # Get text from the main content area
            main_content = soup.select_one("article, .story, .post-content, main")
            text = main_content.get_text(separator=' ', strip=True) if main_content else soup.get_text(separator=' ', strip=True)

            logger.info(f"Extracted {len(text)} characters of text from {post_link} for LLM. HTML length: {len(html)}")
            return text[:10000]  # Limit text length for LLM

        except Exception as e:
            logger.error(f"Error fetching page text for {post_link}: {e}", exc_info=True)
            return ""
