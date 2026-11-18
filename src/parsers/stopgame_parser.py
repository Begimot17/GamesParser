"""StopGame parser for GamesParser project."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.common.logger import logger, missing_data_logger
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.parsers.utils.base_parser import BaseParser


class StopGameParser(BaseParser):
    """Парсер для получения новостей с StopGame.ru."""

    def __init__(self):
        super().__init__(config_key="stopgame", default_url="https://stopgame.ru/news")

    # ── Pagination ────────────────────────────────────────────────────────

    def _build_page_urls(self, pages: int) -> list[str]:
        """Page 1 = base URL, page N = /pN."""
        base = self.TARGET_URLS[0]
        urls = [base]
        for i in range(2, pages + 1):
            urls.append(f"{base}/p{i}")
        return urls

    # ── Store link extraction ─────────────────────────────────────────────

    def _extract_store_links(self, article_html: Tag) -> dict:
        stores: dict = {}
        for link_tag in article_html.find_all("a", href=True):
            href = link_tag.get("href", "")
            for store_name, store_info in self.STORE_CONFIG.items():
                domain = store_info.get("domain")
                if domain and domain in href:
                    cleaned = self._clean_store_url(href, store_name)
                    if cleaned and store_name not in stores:
                        stores[store_name] = cleaned
                        break
        return stores

    # ── Date parsing ──────────────────────────────────────────────────────

    def _extract_id(self, url: str) -> Optional[str]:
        match = re.search(r"(?:newsdata|show)/(\d+)", url)
        return match.group(1) if match else None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date strings like '15 июля 2024 в 23:22' or 'Вчера в 18:00'."""
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

            now = datetime.now(timezone(timedelta(hours=3)))
            if "сегодня" in date_str.lower():
                time_match = re.search(r"(\d{1,2}:\d{2})", date_str)
                time_part = time_match.group(1) if time_match else "00:00"
                date_str = f"{now.strftime('%d %B %Y')} {time_part}"
            elif "вчера" in date_str.lower():
                yesterday = now - timedelta(days=1)
                time_match = re.search(r"(\d{1,2}:\d{2})", date_str)
                time_part = time_match.group(1) if time_match else "00:00"
                date_str = f"{yesterday.strftime('%d %B %Y')} {time_part}"

            for fmt in ("%d %B %Y в %H:%M", "%d %B %Y, %H:%M", "%d %B %Y %H:%M"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.replace(tzinfo=timezone(timedelta(hours=3)))
                except ValueError:
                    continue

            logger.warning("Could not parse StopGame date: %s", date_str)
            return None
        except Exception as e:
            logger.error("Error parsing StopGame date '%s': %s", date_str, e, exc_info=True)
            return None

    # ── Article fetching ──────────────────────────────────────────────────

    async def _fetch_article_data(self, url: str) -> tuple[str, list[str]]:
        """Load full article page and return (content_text, images)."""
        try:
            html = await self._fetch_page(url)
            if not html:
                return "", []
            soup = BeautifulSoup(html, "html.parser")
            content_selector = self.SELECTORS.get("content", "")
            images: list[str] = []
            if content_selector:
                content_elem = soup.select_one(content_selector)
                if content_elem:
                    article_img_selector = self.SELECTORS.get("article_images", "")
                    img_tags = (
                        content_elem.select(article_img_selector) if article_img_selector
                        else content_elem.find_all("img")
                    )
                    for img in img_tags:
                        src = img.get("src") or img.get("data-src")
                        if src and src.startswith("http"):
                            images.append(src)
                    return self._clean_text(content_elem.get_text(" ", strip=True)), images
            for el in soup(["script", "style", "nav", "header", "footer", "aside"]):
                el.decompose()
            main = soup.select_one("article, main, .content")
            return self._clean_text(main.get_text(" ", strip=True) if main else ""), []
        except Exception as e:
            logger.error("Error fetching StopGame article from %s: %s", url, e, exc_info=True)
            return "", []

    # ── Article parsing ───────────────────────────────────────────────────

    def _parse_initial_post_data(self, article_html: Tag) -> Optional[dict]:
        link_elem = article_html.select_one(self.SELECTORS["link"])
        if not link_elem:
            return None
        link = link_elem.get("href")
        if not link:
            return None
        if not link.startswith("https://"):
            link = urljoin(self.TARGET_URLS[0], link)

        article_id = self._extract_id(link)
        if not article_id:
            return None

        title_elem = article_html.select_one(self.SELECTORS["title"])
        image_elem = article_html.select_one(self.SELECTORS["image"])
        date_elem = article_html.select_one(self.SELECTORS["date"])

        return {
            "id": article_id,
            "title": title_elem.get_text(strip=True) if title_elem else "",
            "link": link,
            "image_url": image_elem.get("src") if image_elem else None,
            "date": self._parse_date(date_elem.get_text(strip=True)) if date_elem else None,
        }

    async def _parse_article(self, article_html: Tag, **kwargs) -> Optional[Post]:
        initial_data = self._parse_initial_post_data(article_html)
        if not initial_data:
            return None

        post_id = initial_data["id"]
        link = initial_data["link"]
        if await self._already_known(post_id):
            logger.debug("[StopGameParser] Post %s already processed, skipping fetch", post_id)
            return None
        try:
            title = initial_data["title"]
            images = [initial_data["image_url"]] if initial_data["image_url"] else []
            store_links = self._extract_store_links(article_html)

            content, article_images = await self._fetch_article_data(link)
            images = list(dict.fromkeys(images + article_images))

            if settings.ENABLE_LLM and self.llm:
                title, content, images, store_links = await self._update_post_with_llm_data(
                    title, content, images, link, store_links,
                )

            if not images:
                missing_data_logger.warning("[StopGame] No image | post_id=%s | url=%s", post_id, link)
            if not store_links:
                missing_data_logger.warning(
                    "[StopGame] No store links | post_id=%s | title=%s | url=%s", post_id, title, link,
                )
            elif "steam" not in store_links:
                missing_data_logger.warning(
                    "[StopGame] No Steam link | post_id=%s | title=%s | stores=%s | url=%s",
                    post_id, title, list(store_links.keys()), link,
                )
            if len(content) < 50:
                missing_data_logger.warning(
                    "[StopGame] Content too short (%d chars) | post_id=%s | url=%s", len(content), post_id, link,
                )
            if len(content) > self.MAX_TEXT_LENGTH:
                content = content[:self.MAX_TEXT_LENGTH] + "..."

            game_info_raw = await self._build_game_info_raw(store_links)

            metadata = PostMetadata(
                store_links=store_links,
                images=list(dict.fromkeys(images)),
                date=initial_data["date"],
                game_info=game_info_raw,
            )
            return Post(
                id=post_id, title=title, link=link, content=content, metadata=metadata, source="StopGame",
            )
        except ValidationError as e:
            logger.error("Validation error for StopGame article %s: %s", link, e)
            return None
        except Exception as e:
            logger.error("Error parsing StopGame article %s: %s", link, e, exc_info=True)
            return None
