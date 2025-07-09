import asyncio
import re

import aiohttp

from src.config.config import Config


class BaseParser:
    REQUEST_TIMEOUT: int = Config.REQUEST_TIMEOUT
    RATE_LIMIT_DELAY: int = 2

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
