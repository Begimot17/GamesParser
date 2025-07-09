"""VGTimes parser for GamesParser project."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from src.common import logger
from src.config.config import Config
from src.parsers.utils.base_parser import BaseParser
from src.storage.database import Database


@dataclass
class ArticleMetadata:
    """Metadata for VGTimes article."""

    rating: Optional[int] = None
    store_links: dict = None
    images: list = None
    date: Optional[datetime] = None


@dataclass
class Article:
    """VGTimes article data structure."""

    id: str
    title: str
    link: str
    content: Optional[str] = None
    image_url: Optional[str] = None
    metadata: ArticleMetadata = None

    def dict(self) -> dict:
        """Convert the Article to a dictionary for serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "content": self.content,
            "image_url": self.image_url,
            "metadata": {
                "rating": self.metadata.rating if self.metadata else None,
                "store_links": self.metadata.store_links if self.metadata else None,
                "images": self.metadata.images if self.metadata else None,
                "date": self.metadata.date if self.metadata else None,
            }
            if self.metadata
            else None,
        }


class VGTimesParser(BaseParser):
    """Парсер для получения постов с VGTimes."""

    # Конфигурация парсера
    REQUEST_TIMEOUT = Config.REQUEST_TIMEOUT
    MAX_TEXT_LENGTH = Config.MAX_TEXT_LENGTH
    VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    RATE_LIMIT_DELAY = 2  # Задержка между запросами в секундах
    TARGET_URLS = [
        "https://vgtimes.ru/free/",
    ]

    # CSS селекторы
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
        self.database = Database()

    def _clean_store_url(self, url: str) -> str:
        """Clean and validate store URL."""
        # Remove tracking parameters
        url = re.sub(r"\?.*$", "", url)
        url = re.sub(r"#.*$", "", url)

        # Ensure URL starts with http(s)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        return url

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

    async def fetch_posts(self, url: str = None) -> list:
        """Fetch and parse posts from VGTimes."""
        logger.info("[VGTimesParser] Starting fetch_posts...")
        all_articles = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            logger.info(f"[VGTimesParser] Fetching URL: {target_url}")
            if not target_url.startswith("https"):
                target_url = "https://vgtimes.ru/" + target_url
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0",
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    self.session = session
                    async with session.get(target_url) as response:
                        logger.info(f"[VGTimesParser] Fetching page from {target_url}")
                        html = await response.text()
                        logger.info(f"[VGTimesParser] Got response, length: {len(html)}")
                        articles = self._process_page(html)
                        logger.info(f"[VGTimesParser] Parsed {len(articles)} articles from page")
                        # Fetch full content for each article
                        for article in articles:
                            if article:
                                if self.database.is_processed(article.id):
                                    logger.info(f"[VGTimesParser] Article {article.id} already processed, skipping")
                                    continue
                                content, date = await self._fetch_full_content(article.id, article.link)
                                article.content = content
                                if article.metadata:
                                    if date and date.tzinfo is None:
                                        date = date.replace(tzinfo=timezone(timedelta(hours=3)))
                                    article.metadata.date = date
                        all_articles.extend(articles)
            except Exception as e:
                logger.error(
                    f"[VGTimesParser] Error fetching posts from {target_url}: {e}",
                    exc_info=True,
                )
                continue
        logger.info(f"[VGTimesParser] fetch_posts returning {len(all_articles)} articles")
        return all_articles

    def _process_page(self, html: str) -> list:
        """Process HTML page and extract articles."""
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select(self.SELECTORS["articles"])
        logger.info(
            "Found %d articles on page",
            len(articles),
        )

        parsed_articles = []
        for article in articles:
            if parsed := self._parse_article(article):
                parsed_articles.append(parsed)

        logger.info(
            "Successfully parsed %d posts",
            len(parsed_articles),
        )
        return parsed_articles

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _extract_images(self, article_html) -> list:
        images = []
        image_elem = article_html.select_one(self.SELECTORS["image"])
        if image_elem:
            image_url = image_elem.get("data-src")
            if image_url:
                images.append(image_url)
        for img in article_html.select("img[src]"):
            src = img.get("src") or img.get("data-src")
            if src and src not in images:
                images.append(src)
        return images

    def _extract_date(self, date_elem) -> Optional[datetime]:
        if date_elem:
            date = self._parse_date(date_elem.get_text())
            if date and date.tzinfo is None:
                date = date.replace(tzinfo=timezone(timedelta(hours=3)))
            return date
        return None

    def _extract_rating(self, rating_elem) -> Optional[int]:
        try:
            return int(rating_elem.get_text(strip=True).replace("-", "")) if rating_elem else None
        except (ValueError, TypeError):
            return None

    def _parse_article(self, article_html) -> Optional[Article]:
        try:
            link_elem = article_html.select_one(self.SELECTORS["link"])
            if not link_elem:
                logger.warning("Could not find link element")
                return None
            title = link_elem.get_text(strip=True)
            link = link_elem.get("href")
            if not link.startswith("https"):
                link = "https://vgtimes.ru/" + link
            article_id = self._extract_id(link)
            if not article_id:
                logger.warning(f"Could not extract ID from link: {link}")
                return None
            image_elem = article_html.select_one(self.SELECTORS["image"])
            image_url = image_elem.get("data-src") if image_elem else None
            rating_elem = article_html.select_one(self.SELECTORS["rating"])
            rating = self._extract_rating(rating_elem)
            store_links = self._extract_store_links(article_html)
            content_elem = article_html.select_one(self.SELECTORS["content"])
            content = self._clean_text(content_elem.get_text()) if content_elem else None
            date_elem = article_html.select_one(self.SELECTORS["date"])
            date = self._extract_date(date_elem)
            images = self._extract_images(article_html)
            return Article(
                id=article_id,
                title=title,
                link=link,
                content=content,
                image_url=image_url,
                metadata=ArticleMetadata(
                    rating=rating,
                    store_links=store_links,
                    images=images,
                    date=date,
                ),
            )
        except Exception as e:
            logger.error(f"Error parsing article: {e}", exc_info=True)
            return None

    async def _fetch_full_content(self, post_id: str, post_link: str) -> tuple:
        """Fetch the full content of a post."""
        try:
            # Remove any fragment identifiers from the URL
            clean_url = post_link.split("#")[0]
            logger.info(f"Fetching full content for post {post_id} from {clean_url}")
            if not clean_url.startswith("https"):
                clean_url = "https://vgtimes.ru/" + clean_url

            # Add referer header for the specific article
            headers = {
                "Referer": "https://vgtimes.ru/free/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            async with self.session.get(clean_url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(
                        "Failed to fetch content for post %s, status: %s",
                        post_id,
                        response.status,
                    )
                    return "", None

                html = await response.text()
                logger.info(
                    "Got HTML response for post %s, length: %d",
                    post_id,
                    len(html),
                )
                soup = BeautifulSoup(html, "html.parser")

                # Extract content - try different selectors
                content = ""
                for selector in [
                    "div.article_text",
                    "div.article-content",
                    "div.text_block",
                ]:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        logger.info(f"Found content using selector: {selector}")
                        content = self._clean_text(content_elem.get_text())
                        break

                if not content:
                    logger.warning(
                        "Could not find content for post %s",
                        post_id,
                    )

                # Extract date from JSON-LD metadata
                date = None
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string)
                        if data.get("@type") == "NewsArticle" and data.get("datePublished"):
                            date_str = data["datePublished"].replace("MSK", "")
                            try:
                                # Fix the date format by adding missing separators
                                if "T" not in date_str:
                                    # Format: YYYY-MM-DDHH:MM:SS+00:00
                                    date_str = f"{date_str[:10]}T{date_str[10:]}"
                                # Parse the date and ensure it has timezone info
                                dt = datetime.fromisoformat(date_str)
                                if dt.tzinfo is None:
                                    # If no timezone info, assume MSK (UTC+3)
                                    dt = dt.replace(tzinfo=timezone(timedelta(hours=3)))
                                date = dt
                                logger.info(f"Successfully parsed date from JSON-LD metadata: {date}")
                            except ValueError as e:
                                logger.warning(
                                    "Invalid date format in JSON-LD metadata: %s, error: %s",
                                    date_str,
                                    e,
                                    exc_info=True,
                                )
                            break
                    except (json.JSONDecodeError, AttributeError) as e:
                        logger.warning(f"Error parsing JSON-LD metadata: {e}", exc_info=True)
                        continue

                if not date:
                    # Try to find date in HTML if not found in JSON-LD
                    date_elem = soup.select_one("div.article_date, div.date, time.date")
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                        date = self._parse_date(date_text)
                        if date:
                            logger.info(f"Found date in HTML for post {post_id}: {date}")

                if not date:
                    logger.warning(f"Could not find date for post {post_id}")

                logger.info(f"Successfully fetched content for post {post_id}, content length: {len(content)}")
                return content, date

        except Exception as e:
            logger.error(f"Error fetching content for post {post_id}: {e}", exc_info=True)
            return "", None

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date from string like '5 апреля 2025, 23:22'."""
        try:
            # Remove clock icon if present
            date_str = re.sub(r"<i.*?</i>", "", date_str).strip()
            logger.info(f"Parsing date from HTML: {date_str}")

            # Map Russian month names to English
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

            # Split into date and time parts
            date_parts = date_str.split(",")
            if len(date_parts) != 2:
                logger.warning(f"Invalid date format in HTML: {date_str}")
                return None

            date_part = date_parts[0].strip()
            time_part = date_parts[1].strip()

            # Parse date part
            day, month, year = date_part.split()
            month = ru_to_en.get(month.lower(), "")
            if not month:
                logger.warning(f"Unknown month in date: {date_str}")
                return None

            # Combine and parse
            datetime_str = f"{day} {month} {year} {time_part}"
            # Create naive datetime first
            dt = datetime.strptime(datetime_str, "%d %B %Y %H:%M")
            # Add Moscow timezone (MSK, UTC+3)
            dt = dt.replace(tzinfo=timezone(timedelta(hours=3)))
            logger.info(f"Successfully parsed date from HTML: {dt}")
            return dt

        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}", exc_info=True)
            return None

    def _is_store_url(self, url: str) -> bool:
        """Check if URL is from a game store."""
        store_domains = [
            "store.steampowered.com",
            "epicgames.com",
            "gog.com",
            "xbox.com",
            "playstation.com",
            "nintendo.com",
            "itch.io",
        ]
        return any(domain in url.lower() for domain in store_domains)

    def _extract_post_id(self, url: str) -> str:
        """Extract post ID from URL."""
        try:
            # URL format: https://vgtimes.ru/free/123799-v-steam-stal-vremenno-besplatnym-avtobattler-mechabellum.html
            parts = url.split("/")
            if len(parts) < 2:
                return ""

            # Get the last part before .html
            last_part = parts[-1].split(".")[0]

            # Extract the numeric ID
            match = re.search(r"^(\d+)", last_part)
            if not match:
                return ""

            return match.group(1)

        except Exception as e:
            logger.error(f"Error extracting post ID from URL {url}: {e}", exc_info=True)
            return ""
