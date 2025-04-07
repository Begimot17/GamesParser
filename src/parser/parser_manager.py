import asyncio
import logging
from typing import List

from src.models.models import Post
from src.parser.dtf_parser import DTFParser
from src.parser.vgtimes_parser import VGTimesParser

logger = logging.getLogger(__name__)


class ParserManager:
    def __init__(self):
        self.parsers = [DTFParser(), VGTimesParser()]

    async def fetch_all_posts(self) -> List[Post]:
        """Получение постов со всех источников"""
        all_posts = []
        for parser in self.parsers:
            try:
                async with parser:
                    posts = await parser.fetch_posts()
                    all_posts.extend(posts)
            except Exception as e:
                logger.error("Ошибка при работе с парсером: %s", str(e), exc_info=True)
                continue
        return all_posts 