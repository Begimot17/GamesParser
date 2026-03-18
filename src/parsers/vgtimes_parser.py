"""VGTimes parser for GamesParser project."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from src.common.logger import logger, missing_data_logger
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser


class VGTimesParser(BaseParser):
    """Парсер для получения постов с VGTimes."""

    def __init__(self):
        super().__init__(config_key="vgtimes", default_url="https://vgtimes.ru/free/")

    # ── Pagination ────────────────────────────────────────────────────────

    def _build_page_urls(self, pages: int) -> list[str]:
        """Page 1 = base URL, page N = ?PAGEN_1=N."""
        base = self.TARGET_URLS[0].rstrip("/") + "/"
        urls = [base]
        for i in range(2, pages + 1):
            urls.append(f"{base}?PAGEN_1={i}")
        return urls

    # ── URL processing (concurrent with semaphore) ────────────────────────

    async def _process_url(self, target_url: str) -> AsyncGenerator:
        html = ""
        try:
            await self._rate_limit()
            logger.info("[VGTimesParser] Processing page: %s", target_url)
            html = await self._fetch_page(target_url)
            logger.info("[VGTimesParser] Got response, length: %d", len(html))

            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(self.SELECTORS["articles"])
            logger.info("[VGTimesParser] Found %d articles on page", len(articles))

            sem = asyncio.Semaphore(3)

            async def _fetch_with_sem(article):
                async with sem:
                    return await self._parse_article(article)

            results = await asyncio.gather(*[_fetch_with_sem(a) for a in articles], return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("[VGTimesParser] Article parse error: %s", result)
                elif result:
                    logger.info("[VGTimesParser] Yielding post %s", result.id)
                    yield result
        except Exception as e:
            logger.error("[VGTimesParser] Unexpected error for %s: %s", target_url, e, exc_info=True)
            if html:
                self._save_html_on_error(html, target_url)

    # ── Store link extraction ─────────────────────────────────────────────

    def _clean_store_url(self, url: str, store_name: str) -> str:
        """Handle VGTimes /go/ redirect URLs before standard cleaning."""
        if url and "/go/" in url:
            parsed = urlparse(url)
            if parsed.query:
                decoded = unquote(parsed.query)
                if decoded.startswith("http"):
                    url = decoded.split("&")[0]
                    logger.debug("Decoded VGTimes go-URL: %s", url)
        return super()._clean_store_url(url, store_name)

    def _extract_store_links(self, article_html: Tag) -> dict:
        stores: dict = {}
        for link in article_html.select(self.SELECTORS.get("store_links", "")):
            href = link.get("href", "")
            for store_name, store_info in self.STORE_CONFIG.items():
                domain = store_info.get("domain")
                if domain and domain in href:
                    cleaned = self._clean_store_url(href, store_name)
                    if cleaned:
                        stores[store_name] = cleaned
                        break
        return stores

    # ── Date parsing ──────────────────────────────────────────────────────

    def _extract_id(self, url: str) -> Optional[str]:
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse strings like '5 апреля 2025, 23:22', 'Вчера, 15:58', 'Сегодня, 15:58'."""
        logger.info("[VGTimesParser] Parsing date: '%s'", date_str)
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
            logger.error("Error parsing VGTimes date '%s': %s", date_str, e, exc_info=True)
            return None

    # ── Article parsing ───────────────────────────────────────────────────

    async def _parse_article(self, article_html: Tag, **kwargs) -> Optional[Post]:
        link_elem = article_html.select_one(self.SELECTORS["link"])
        if not link_elem:
            logger.warning("[VGTimesParser] No link element found in article")
            return None

        link = link_elem.get("href")
        if not link:
            logger.warning("[VGTimesParser] Link element has empty href")
            return None
        if not link.startswith("https://"):
            link = urljoin(self.TARGET_URLS[0], link)

        article_id = self._extract_id(link)
        if not article_id:
            logger.warning("[VGTimesParser] Could not extract article ID from: %s", link)
            return None

        title_elem = article_html.select_one(self.SELECTORS["title"])
        title = title_elem.get_text(strip=True) if title_elem else ""
        if not title:
            logger.warning("[VGTimesParser] No title for article %s", article_id)

        image_elem = article_html.select_one(self.SELECTORS["image"])
        image_url = (image_elem.get("data-src") or image_elem.get("src")) if image_elem else None
        if not image_url:
            missing_data_logger.warning("[VGTimes] No image | post_id=%s | url=%s", article_id, link)

        rating_elem = article_html.select_one(self.SELECTORS["rating"])
        rating = rating_elem.get_text(strip=True) if rating_elem else None

        try:
            full_html = await self._fetch_page(link)
            soup = BeautifulSoup(full_html, "html.parser")

            content_elem = soup.select_one(self.SELECTORS["content"])
            content = content_elem.get_text(" ", strip=True) if content_elem else ""

            date_elem = soup.select_one(self.SELECTORS["date"])
            raw_date = date_elem.get_text(strip=True) if date_elem else ""
            date = self._parse_date(raw_date) if raw_date else None

            store_links = self._extract_store_links(article_html)
            content = self._clean_text(content)

            if len(content) < 50:
                missing_data_logger.warning(
                    "[VGTimes] Content too short (%d chars) | post_id=%s | url=%s", len(content), article_id, link,
                )
            if len(content) > self.MAX_TEXT_LENGTH:
                content = content[:self.MAX_TEXT_LENGTH] + "..."

            if not store_links:
                missing_data_logger.info(
                    "[VGTimes] No store links (expected for news/giveaway) | post_id=%s | title=%s | url=%s",
                    article_id, title, link,
                )
            elif "steam" not in store_links:
                missing_data_logger.warning(
                    "[VGTimes] No Steam link | post_id=%s | title=%s | stores=%s | url=%s",
                    article_id, title, list(store_links.keys()), link,
                )

            game_info_raw = await self._build_game_info_raw(store_links)

            metadata = PostMetadata(
                rating=rating,
                store_links=store_links,
                images=[self._normalize_url(image_url)] if image_url else [],
                date=date,
                game_info=game_info_raw,
            )
            return Post(
                id=article_id, title=title, link=link, content=content, metadata=metadata, source="VGTimes",
            )
        except Exception as e:
            logger.error("[VGTimesParser] Error parsing article %s: %s", article_id, e, exc_info=True)
            return None
