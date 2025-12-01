import os

import aiohttp
from bs4 import BeautifulSoup

from src.common.logger import logger
from src.config.config import Config
from src.models.post import Post


class StopGameParser:
    """Парсер для сайта StopGame.ru."""

    def __init__(self, url: str):
        self.url = url

    async def fetch_page(self, session: aiohttp.ClientSession, url: str) -> str | None:
        """Загружает содержимое страницы."""
        try:
            async with session.get(url, timeout=Config.REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                html = await response.text()
                if Config.SAVE_HTML:
                    self._save_html(html, url)
                return html
        except aiohttp.ClientError as e:
            logger.error(f"Error fetching page {url}: {e}")
            return None

    def _save_html(self, html: str, url: str) -> None:
        """Сохраняет HTML-код страницы в файл."""
        if not os.path.exists(Config.HTML_DIR):
            os.makedirs(Config.HTML_DIR)
        filename = f"{url.replace('/', '_').replace(':', '')}.html"
        filepath = os.path.join(Config.HTML_DIR, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"Saved HTML for {url} to {filepath}")
        except IOError as e:
            logger.error(f"Error saving HTML for {url}: {e}")

    async def parse_posts(self, html: str) -> list[Post]:
        """Парсит посты из HTML-кода."""
        soup = BeautifulSoup(html, "html.parser")
        # Implement parsing logic here
        return []

    async def get_posts(self) -> list[Post]:
        """Получает все посты."""
        async with aiohttp.ClientSession() as session:
            html = await self.fetch_page(session, self.url)
            if html:
                return await self.parse_posts(html)
            return []
