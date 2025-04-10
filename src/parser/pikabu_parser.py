import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

from src.config.config import Config
from src.models.models import Post, PostMetadata

logger = logging.getLogger(__name__)


class PikabuParser:
    # Конфигурация парсера
    REQUEST_TIMEOUT = Config.REQUEST_TIMEOUT
    MAX_TEXT_LENGTH = Config.MAX_TEXT_LENGTH
    VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    RATE_LIMIT_DELAY = 2  # Задержка между запросами в секундах
    TARGET_URL = "https://pikabu.ru/community/steam"

    # CSS селекторы
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
        """Очистка текста от отступов, лишних пробелов и 'Показать полностью' с цифрой"""
        if not text:
            return ""
        # Удаляем все отступы и лишние пробелы
        text = re.sub(r"\s+", " ", text)
        # Удаляем "Показать полностью" и следующую за ней цифру
        text = re.sub(r"Показать полностью\s*\d+", "", text)
        # Удаляем пробелы в начале и конце
        text = text.strip()
        return text

    def _clean_store_url(self, url: str) -> str:
        """Очистка и проверка URL магазина"""
        if not url:
            return ""

        # Нормализуем URL
        url = self._normalize_url(url)

        # Удаляем параметры отслеживания и реферальные ссылки
        url = url.split("?")[0]
        url = url.split("#")[0]

        # Проверяем, что это ссылка на конкретный товар, а не на главную страницу
        if "store.steampowered.com" in url:
            # Для Steam проверяем наличие /app/ и ID приложения
            if not re.search(r"/app/\d+/", url):
                return ""
        elif "epicgames.com" in url:
            # Для Epic Games проверяем наличие /p/ и ID продукта
            if not re.search(r"/p/[^/]+$", url):
                return ""
        elif "itch.io" in url:
            # Для itch.io проверяем, что это не главная страница и есть название игры
            if url.rstrip("/").count("/") < 3 or url.endswith("/itch.io"):
                return ""
        elif "gog.com" in url:
            # Для GOG проверяем наличие /game/ и название игры
            if not re.search(r"/game/[^/]+$", url):
                return ""
        else:
            return ""

        return url

    def _extract_store_links(self, text: str) -> Dict[str, str]:
        """Извлечение ссылок на магазины из текста"""
        stores = {}
        # Ищем ссылки в тексте
        for store_name, pattern in self.store_patterns.items():
            # Ищем ссылки в формате [store_name](url)
            store_links = re.findall(
                rf"\[{store_name}\]\((https?://[^)]+)\)", text, re.IGNORECASE
            )
            if store_links:
                cleaned_url = self._clean_store_url(store_links[0])
                if cleaned_url:
                    stores[store_name] = cleaned_url
                continue
            # Ищем прямые ссылки на магазины
            store_links = re.findall(rf'https?://[^"\s]+{pattern.pattern}[^"\s]*', text)
            if store_links:
                cleaned_url = self._clean_store_url(store_links[0])
                if cleaned_url:
                    if "/accounts/" in cleaned_url:
                        continue
                    stores[store_name] = cleaned_url
        return stores

    async def fetch_posts(self) -> List[Post]:
        """Основной метод для получения и обработки постов"""
        try:
            await self._rate_limit()
            response = await self._fetch_page(self.TARGET_URL)
            return self._process_page(response)
        except Exception as e:
            logger.error(
                "Неожиданная ошибка при парсинге DTF: %s", str(e), exc_info=True
            )
            return []

    async def _fetch_page(self, url: str) -> str:
        """Выполнение HTTP запроса с повторными попытками"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession(headers=self.headers)
                async with self.session.get(
                    url, timeout=self.REQUEST_TIMEOUT
                ) as response:
                    response.raise_for_status()
                    return await response.text()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning("Попытка %d не удалась: %s", attempt + 1, str(e))
                await asyncio.sleep(2**attempt)  # Экспоненциальная задержка

    def _process_page(self, html: str) -> List[Post]:
        """Обработка HTML страницы"""
        try:
            soup = BeautifulSoup(html, "html.parser")
            posts = []

            for article in soup.select(self.SELECTORS["articles"]):
                try:
                    post = self._parse_article(article)
                    if post:
                        posts.append(post)
                except Exception as e:
                    logger.error(
                        "Ошибка при парсинге статьи DTF: %s", str(e), exc_info=True
                    )
                    continue

            return posts
        except Exception as e:
            logger.error("Ошибка при обработке страницы DTF: %s", str(e), exc_info=True)
            return []

    def _normalize_url(self, url: str, base_url: str = None) -> str:
        """Нормализация URL"""
        if not url:
            return ""

        try:
            # Если URL начинается с //, добавляем https:
            if url.startswith("//"):
                url = f"https:{url}"
            # Если URL начинается с /, добавляем базовый URL
            elif url.startswith("/"):
                base_url = base_url or self.TARGET_URL
                url = urljoin(base_url, url)
            # Если URL не содержит схему, добавляем https://
            elif not urlparse(url).scheme:
                url = f"https://{url}"

            return url
        except Exception as e:
            logger.error("Ошибка при нормализации URL %s: %s", url, str(e))
            return ""

    def _parse_article(self, article: Tag) -> Optional[Post]:
        """Парсинг статьи с главной страницы DTF"""
        try:
            # Получаем ID поста
            post_id = article.get("data-story-id")
            if not post_id:
                logger.warning("No post ID found in DTF article")
                return None

            # Получаем заголовок
            title_element = article.select_one(self.SELECTORS["title"])
            if not title_element:
                logger.warning("No title found for DTF post %s", post_id)
                return None
            title = self._clean_text(title_element.text)
            if not title:
                logger.warning("Empty title for DTF post %s", post_id)
                return None

            # Получаем ссылку
            link = self._normalize_url(title_element.get("href", ""))
            if not link:
                logger.warning("No link found for DTF post %s", post_id)
                return None

            # Получаем рейтинг
            rating_element = article.select_one(self.SELECTORS["rating"])
            rating = self._clean_text(rating_element.text) if rating_element else "0"

            # Получаем дату
            date = None
            date_element = article.select_one(self.SELECTORS["date"])
            if date_element:
                date_str = date_element.get("datetime")
                if date_str:
                    try:
                        logger.info(
                            f"Found date in HTML for DTF post {post_id}: {date_str}"
                        )
                        date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        logger.info(
                            f"Successfully parsed date for DTF post {post_id}: {date}"
                        )
                    except ValueError:
                        logger.warning(
                            "Invalid date format for DTF post %s: %s", post_id, date_str
                        )
            else:
                logger.warning(f"No date element found for DTF post {post_id}")

            # Получаем контент
            content_element = article.select_one(self.SELECTORS["content"])
            content = self._clean_text(content_element.text) if content_element else ""

            # Получаем изображения
            images = []
            for selector in self.SELECTORS["images"]:
                for img in article.select(selector):
                    src = img.get("src") or img.get("data-src")
                    if src:
                        src = self._normalize_url(src)
                        if src and any(
                            src.endswith(ext) for ext in self.VALID_IMAGE_EXTENSIONS
                        ):
                            if "/avatars/" in src:
                                continue
                            images.append(src)

            # Извлекаем ссылки на магазины
            store_links = self._extract_store_links(content)

            # Создаем метаданные
            metadata = PostMetadata(
                rating=rating, store_links=store_links, images=images, date=date
            )

            return Post(
                id=post_id,
                title=title,
                link=link,
                content=content,
                date=date,
                metadata=metadata,
            )

        except Exception as e:
            logger.error("Ошибка при парсинге статьи DTF: %s", str(e), exc_info=True)
            return None
