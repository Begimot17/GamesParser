"""VGTimes parser for GamesParser project."""

import re
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, AsyncIterator, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from src.common.logger import logger
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser
from src.services.llm_g4f import LLMG4F
from src.services.price_service import PriceService


class VGTimesParser(BaseParser):
    """Парсер для получения постов с VGTimes."""

    def __init__(self):
        self.config = settings.PARSERS_CONFIG.get("vgtimes", {})
        if not self.config:
            logger.warning("VGTimes configuration not found in settings! Using defaults.")
            self.TARGET_URLS = ["https://vgtimes.ru/free/"]
        else:
            self.TARGET_URLS = (
                self.config.get("target_urls", "").split(",")
                if isinstance(self.config.get("target_urls"), str)
                else self.config.get("target_urls", [])
            )

        super().__init__(default_base_url=self.TARGET_URLS[0] if self.TARGET_URLS else None)

        self.REQUEST_TIMEOUT = self.config.get("request_timeout", settings.REQUEST_TIMEOUT)
        self.MAX_TEXT_LENGTH = self.config.get("max_text_length", settings.MAX_TEXT_LENGTH)
        self.VALID_IMAGE_EXTENSIONS = tuple(self.config.get("valid_image_extensions", [".jpg", ".jpeg", ".png", ".gif", ".webp"]))
        self.RATE_LIMIT_DELAY = self.config.get("rate_limit_delay", 2)
        self.SELECTORS = self.config.get("selectors", {})
        self.STORE_CONFIG = self.config.get("stores", {})

        self.llm = LLMG4F(model_name=settings.LLM_MODEL)
        self.price_service = PriceService()

    def _clean_store_url(self, url: str, store_name: str) -> str:
        """Очистка и проверка URL магазина с поддержкой /go/ редиректов VGTimes."""
        if not url:
            return ""

        if "/go/" in url:
            parsed = urlparse(url)
            if parsed.query:
                decoded = unquote(parsed.query)
                if decoded.startswith("http"):
                    url = decoded.split("&")[0]
                    logger.debug(f"Decoded go-URL: {url}")

        return super()._clean_store_url(url, store_name)

    def _extract_store_links(self, article_html: Tag) -> dict:
        """Extract store links from article."""
        stores: dict = {}
        link_elements = article_html.select(self.SELECTORS.get("store_links", ""))
        for link in link_elements:
            href = link.get("href", "")
            for store_name, store_info in self.STORE_CONFIG.items():
                domain = store_info.get("domain")
                if domain and domain in href:
                    cleaned_url = self._clean_store_url(href, store_name)
                    if cleaned_url:
                        stores[store_name] = cleaned_url
                        break
        return stores

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
                    post = await self._parse_article(article)
                    if post:
                        logger.info(f"[VGTimesParser] Yielding post {post.id}")
                        yield post
                except Exception as e:
                    logger.error(f"[VGTimesParser] Error processing individual article: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[VGTimesParser] Unexpected error in _process_url for {target_url}: {e}", exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    async def fetch_posts(self, url: Optional[str] = None) -> list[Post]:
        """Fetch and parse posts from VGTimes."""
        logger.info("[VGTimesParser] Starting fetch_posts...")
        all_posts: list[Post] = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            async for post in self._process_url(target_url):
                all_posts.append(post)
        logger.info(f"[VGTimesParser] fetch_posts completed. Total posts: {len(all_posts)}")
        return all_posts

    async def stream_posts(self) -> AsyncGenerator[Post, None]:
        """Генератор для потокового получения статей по мере их парсинга."""
        logger.info("[VGTimesParser] Starting stream_posts...")
        for target_url in self.TARGET_URLS:
            async for post in self._process_url(target_url):
                yield post
        logger.info("[VGTimesParser] stream_posts completed")

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date from string like '5 апреля 2025, 23:22', 'Вчера, 15:58', or 'Сегодня, 15:58'."""
        logger.info(f"[VGTimesParser] Attempting to parse date string: '{date_str}'")
        try:
            date_str = re.sub(r"<i.*?</i>", "", date_str).strip()
            now = datetime.now(timezone(timedelta(hours=3)))

            if "Вчера" in date_str:
                time_str = date_str.split(",")[1].strip()
                yesterday = now - timedelta(days=1)
                dt = datetime.strptime(f"{yesterday.strftime('%d %m %Y')} {time_str}", "%d %m %Y %H:%M")
                return dt.replace(tzinfo=timezone(timedelta(hours=3)))

            if "Сегодня" in date_str:
                time_str = date_str.split(",")[1].strip()
                dt = datetime.strptime(f"{now.strftime('%d %m %Y')} {time_str}", "%d %m %Y %H:%M")
                return dt.replace(tzinfo=timezone(timedelta(hours=3)))

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

    async def _parse_article(self, article_html: Tag) -> Optional[Post]:
        """Парсинг одной статьи со страницы списка."""
        link_elem = article_html.select_one(self.SELECTORS["link"])
        if not link_elem:
            logger.warning("[VGTimesParser] No link element found in article on list page.")
            return None

        link = link_elem.get("href")
        if not link:
            logger.warning("[VGTimesParser] Link element found but href attribute is empty.")
            return None

        if not link.startswith("https://"):
            link = urljoin(self.TARGET_URLS[0], link)

        article_id = self._extract_id(link)
        if not article_id:
            logger.warning(f"[VGTimesParser] Could not extract article ID from link: {link}")
            return None

        title_elem = article_html.select_one(self.SELECTORS["title"])
        title = title_elem.get_text(strip=True) if title_elem else ""
        if not title:
            logger.warning(f"[VGTimesParser] No title found for article {article_id}")

        image_elem = article_html.select_one(self.SELECTORS["image"])
        image_url = image_elem.get("data-src") if image_elem else None
        if not image_url:
            image_url = image_elem.get("src") if image_elem else None

        rating_elem = article_html.select_one(self.SELECTORS["rating"])
        rating = rating_elem.get_text(strip=True) if rating_elem else None

        try:
            full_article_html = await self._fetch_page(link)
            soup = BeautifulSoup(full_article_html, "html.parser")

            content_elem = soup.select_one(self.SELECTORS["content"])
            content = content_elem.get_text(" ", strip=True) if content_elem else ""

            date_elem = soup.select_one(self.SELECTORS["date"])
            raw_date_text = date_elem.get_text(strip=True) if date_elem else ""
            date = self._parse_date(raw_date_text) if raw_date_text else None

            store_links = self._extract_store_links(article_html)

            content = self._clean_text(content)

            if len(content) > self.MAX_TEXT_LENGTH:
                content = content[:self.MAX_TEXT_LENGTH] + "..."

            game_info_raw = {}
            if store_links:
                try:
                    infos = await self.price_service.get_all_info(store_links)
                    game_info_raw = {
                        store: (info.to_dict() if info and not isinstance(info, list) else
                                [i.to_dict() if i else None for i in info] if isinstance(info, list) else None)
                        for store, info in infos.items()
                    }
                except Exception as e:
                    logger.warning("[VGTimesParser] Failed to fetch game info: %s", e)

            metadata = PostMetadata(
                rating=rating,
                store_links=store_links,
                images=[self._normalize_url(image_url)] if image_url else [],
                date=date,
                game_info=game_info_raw,
            )

            return Post(
                id=article_id,
                title=title,
                link=link,
                content=content,
                metadata=metadata,
                source="VGTimes",
            )

        except Exception as e:
            logger.error(f"[VGTimesParser] Error parsing article {article_id}: {e}", exc_info=True)
            return None
