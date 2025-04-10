import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

from src.config.config import Config
from src.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class ArticleMetadata:
    rating: Optional[int] = None
    store_links: Dict[str, str] = None
    images: List[str] = None
    date: Optional[datetime] = None

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


@dataclass
class Article:
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


class VGTimesParser:
    # Конфигурация парсера
    REQUEST_TIMEOUT = Config.REQUEST_TIMEOUT
    MAX_TEXT_LENGTH = Config.MAX_TEXT_LENGTH
    VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    RATE_LIMIT_DELAY = 2  # Задержка между запросами в секундах
    TARGET_URLS = [
        "https://vgtimes.ru/free/",
        "https://vgtimes.ru/gaming-news/",
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
        self.headers = {"User-Agent": Config.USER_AGENT}
        self.store_patterns = {
            "Steam": re.compile(r"store\.steampowered\.com"),
            "Epic Games": re.compile(r"epicgames\.com"),
            "GOG": re.compile(r"gog\.com"),
            "itch.io": re.compile(r"itch\.io"),
        }
        self.last_request_time = 0
        self.session = None
        self.database = Database()

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _rate_limit(self) -> None:
        """Ограничение частоты запросов"""
        current_time = asyncio.get_event_loop().time()
        if current_time - self.last_request_time < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(
                self.RATE_LIMIT_DELAY - (current_time - self.last_request_time)
            )
        self.last_request_time = current_time

    def _clean_text(self, text: str) -> str:
        """Clean text content."""
        if not text:
            return ""

        # Remove extra whitespace and newlines
        text = re.sub(r"\s+", " ", text)
        text = text.strip()

        # Remove script and style elements
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL)

        return text

    def _clean_store_url(self, url: str) -> str:
        """Clean and validate store URL."""
        # Remove tracking parameters
        url = re.sub(r"\?.*$", "", url)
        url = re.sub(r"#.*$", "", url)

        # Ensure URL starts with http(s)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        return url

    def _extract_store_links(self, article_html) -> Dict[str, str]:
        """Extract store links from article"""
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

    async def fetch_posts(self, url: str = None) -> List[Article]:
        """Fetch and parse posts from VGTimes"""
        all_articles = []
        urls = [url] if url else self.TARGET_URLS

        for target_url in urls:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0",
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    self.session = session
                    async with session.get(target_url) as response:
                        logger.info(f"Fetching page from {target_url}")
                        html = await response.text()
                        logger.info(f"Got response, length: {len(html)}")
                        articles = self._process_page(html)

                        # Fetch full content for each article
                        for article in articles:
                            if article:
                                # Skip if article is already in database
                                if self.database.is_processed(article.id):
                                    logger.info(f"Article {article.id} already processed, skipping")
                                    continue
                                    
                                content, date = await self._fetch_full_content(
                                    article.id, article.link
                                )
                                article.content = content
                                if article.metadata:
                                    # Ensure date is timezone-aware
                                    if date and date.tzinfo is None:
                                        date = date.replace(
                                            tzinfo=timezone(timedelta(hours=3))
                                        )
                                    article.metadata.date = date

                        all_articles.extend(articles)
            except Exception as e:
                logger.error(f"Error fetching posts from {target_url}: {e}")
                continue

        return all_articles

    def _process_page(self, html: str) -> List[Article]:
        """Process HTML page and extract articles"""
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select(self.SELECTORS["articles"])
        logger.info(f"Found {len(articles)} articles on page")

        parsed_articles = []
        for article in articles:
            if parsed := self._parse_article(article):
                parsed_articles.append(parsed)

        logger.info(f"Successfully parsed {len(parsed_articles)} posts")
        return parsed_articles

    def _extract_id(self, url: str) -> Optional[str]:
        """Extract article ID from URL"""
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else None

    def _parse_article(self, article_html) -> Optional[Article]:
        """Parse a single article element"""
        try:
            # Find title and link
            link_elem = article_html.select_one(self.SELECTORS["link"])
            if not link_elem:
                logger.warning("Could not find link element")
                return None

            title = link_elem.get_text(strip=True)
            link = link_elem.get("href")

            # Extract ID from link
            article_id = self._extract_id(link)
            if not article_id:
                logger.warning(f"Could not extract ID from link: {link}")
                return None

            # Find image URL
            image_elem = article_html.select_one(self.SELECTORS["image"])
            image_url = image_elem.get("data-src") if image_elem else None

            # Find rating
            rating_elem = article_html.select_one(self.SELECTORS["rating"])
            try:
                rating = int(rating_elem.get_text(strip=True).replace("-", "")) if rating_elem else None
            except (ValueError, TypeError):
                rating = None

            # Extract store links
            store_links = self._extract_store_links(article_html)

            # Find content
            content_elem = article_html.select_one(self.SELECTORS["content"])
            content = (
                self._clean_text(content_elem.get_text()) if content_elem else None
            )

            # Find date and ensure it's timezone-aware
            date_elem = article_html.select_one(self.SELECTORS["date"])
            date = None
            if date_elem:
                date = self._parse_date(date_elem.get_text())
                if date and date.tzinfo is None:
                    # If no timezone info, assume MSK (UTC+3)
                    date = date.replace(tzinfo=timezone(timedelta(hours=3)))

            # Collect all images
            images = []
            if image_url:
                images.append(image_url)
            for img in article_html.select("img[src]"):
                src = img.get("src") or img.get("data-src")
                if src and src not in images:
                    images.append(src)

            return Article(
                id=article_id,
                title=title,
                link=link,
                content=content,
                image_url=image_url,
                metadata=ArticleMetadata(
                    rating=rating, store_links=store_links, images=images, date=date
                ),
            )
        except Exception as e:
            logger.error(f"Error parsing article: {e}")
            return None

    async def _fetch_full_content(
        self, post_id: str, post_link: str
    ) -> Tuple[str, datetime]:
        """Fetch the full content of a post."""
        try:
            # Remove any fragment identifiers from the URL
            clean_url = post_link.split("#")[0]
            logger.info(f"Fetching full content for post {post_id} from {clean_url}")

            # Add referer header for the specific article
            headers = {
                "Referer": "https://vgtimes.ru/free/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            async with self.session.get(clean_url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(
                        f"Failed to fetch content for post {post_id}, status: {response.status}"
                    )
                    return "", None

                html = await response.text()
                logger.info(
                    f"Got HTML response for post {post_id}, length: {len(html)}"
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
                    logger.warning(f"Could not find content for post {post_id}")

                # Extract date from JSON-LD metadata
                date = None
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string)
                        if data.get("@type") == "NewsArticle" and data.get(
                            "datePublished"
                        ):
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
                                logger.info(
                                    f"Successfully parsed date from JSON-LD metadata: {date}"
                                )
                            except ValueError as e:
                                logger.warning(
                                    f"Invalid date format in JSON-LD metadata: {date_str}, error: {e}"
                                )
                            break
                    except (json.JSONDecodeError, AttributeError) as e:
                        logger.warning(f"Error parsing JSON-LD metadata: {e}")
                        continue

                if not date:
                    # Try to find date in HTML if not found in JSON-LD
                    date_elem = soup.select_one("div.article_date, div.date, time.date")
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                        date = self._parse_date(date_text)
                        if date:
                            logger.info(
                                f"Found date in HTML for post {post_id}: {date}"
                            )

                if not date:
                    logger.warning(f"Could not find date for post {post_id}")

                logger.info(
                    f"Successfully fetched content for post {post_id}, content length: {len(content)}"
                )
                return content, date

        except Exception as e:
            logger.error(f"Error fetching content for post {post_id}: {e}")
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
            logger.error(f"Error parsing date '{date_str}': {e}")
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
            logger.error(f"Error extracting post ID from URL {url}: {e}")
            return ""
