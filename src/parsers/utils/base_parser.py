import asyncio
import os
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import quote, urlparse, urljoin

import aiohttp
import aiofiles # Added import for aiofiles

from src.common.logger import logger
from src.config.config import Config


class BaseParser(ABC):
    REQUEST_TIMEOUT: int = Config.REQUEST_TIMEOUT
    RATE_LIMIT_DELAY: int = 2

    def __init__(self, default_base_url: Optional[str] = None):
        self.headers = {"User-Agent": Config.USER_AGENT}
        self.last_request_time = 0
        self.session = None
        self.default_base_url = default_base_url

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _rate_limit(self) -> None:
        current_time = asyncio.get_event_loop().time()
        if current_time - self.last_request_time < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - (current_time - self.last_request_time))
        self.last_request_time = current_time

    def _clean_text(self, text: str) -> str:
        """Очистка текста от лишних символов, пробелов и html-тегов."""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL)
        text = text.strip()
        return text

    def _normalize_url(self, url: str, base_url: Optional[str] = None) -> str:
        """Нормализация URL."""
        if not url:
            return ""
        
        # Use instance's default_base_url if base_url is not provided
        effective_base_url = base_url if base_url is not None else self.default_base_url

        try:
            if url.startswith("//"):
                url = f"https:{url}"
            elif url.startswith("/"):
                if not effective_base_url:
                    logger.warning(f"Relative URL '{url}' provided without a base_url or default_base_url for normalization.")
                    return ""
                url = urljoin(effective_base_url, url)
            elif not urlparse(url).scheme:
                url = f"https://{url}"
            return url
        except Exception as e:
            logger.error(f"Ошибка при нормализации URL {url}: {e}")
            return ""

    def _save_html_on_error(self, html: str, url: str) -> None:
        """Saves the HTML content to a file on parsing error."""
        if not Config.SAVE_HTML:
            return

        if not os.path.exists(Config.HTML_DIR):
            os.makedirs(Config.HTML_DIR)
        
        # Sanitize the URL to create a valid filename
        filename = f"{quote(url, safe='')}.html"
        filepath = os.path.join(Config.HTML_DIR, filename)
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"Saved HTML for {url} to {filepath}")
        except IOError as e:
            logger.error(f"Error saving HTML for {url}: {e}")

    async def _save_fetched_html(self, html_content: str, url: str) -> None:
        """Saves all fetched HTML content to a file."""
        if not Config.SAVE_ALL_FETCHED_HTML:
            logger.debug(f"Skipping saving fetched HTML for {url}: SAVE_ALL_FETCHED_HTML is false.")
            return

        if not os.path.exists(Config.FETCHED_HTML_DIR):
            logger.info(f"Creating directory for fetched HTML: {Config.FETCHED_HTML_DIR}")
            os.makedirs(Config.FETCHED_HTML_DIR)
        
        filename = f"{quote(url, safe='')}.html"
        filepath = os.path.join(Config.FETCHED_HTML_DIR, filename)
        
        try:
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(html_content)
            logger.info(f"Saved fetched HTML for {url} to {filepath}")
        except IOError as e:
            logger.error(f"Error saving fetched HTML for {url}: {e}")

    async def _fetch_page(self, url: str) -> str:
        """Выполнение HTTP запроса с повторными попытками."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.session or self.session.closed:
                    self.session = aiohttp.ClientSession(headers=self.headers)
                async with self.session.get(url, timeout=self.REQUEST_TIMEOUT) as response:
                    response.raise_for_status()
                    html_content = await response.text()
                    await self._save_fetched_html(html_content, self.__class__.__name__) # Save fetched HTML
                    return html_content
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}", exc_info=True)
                    raise
                logger.warning(f"Attempt {attempt + 1} to fetch {url} failed: {e}. Retrying...")
                await asyncio.sleep(2**attempt)
        return ""

    @abstractmethod
    async def fetch_posts(self) -> list:
        """Получить все посты сразу (старый метод)."""

    @abstractmethod
    async def stream_posts(self):
        """Генератор для потокового получения постов по мере их парсинга."""
