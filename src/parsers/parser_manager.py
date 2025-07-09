"""Parser manager for GamesParser project."""

from common import logger
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.vgtimes_parser import VGTimesParser


class ParserManager:
    """Менеджер парсеров."""

    def __init__(self):
        """Инициализация ParserManager."""
        logger.info("[ParserManager] Initializing parser manager...")
        self.parsers = [VGTimesParser(), PikabuParser()]
        logger.info(f"[ParserManager] Parsers initialized: {[type(p).__name__ for p in self.parsers]}")

    async def fetch_all_posts(self) -> list:
        """Получение постов со всех источников."""
        logger.info("[ParserManager] Fetching posts from all parsers...")
        all_posts: list = []
        for parser in self.parsers:
            logger.info(f"[ParserManager] Fetching posts using {type(parser).__name__}")
            try:
                async with parser:
                    posts = await parser.fetch_posts()
                    logger.info(f"[ParserManager] {type(parser).__name__} returned {len(posts)} posts")
                    all_posts.extend(posts)
            except Exception as e:
                logger.error(f"[ParserManager] Error fetching posts from {type(parser).__name__}: {e}", exc_info=True)
                return []
        logger.info(f"[ParserManager] Total posts fetched: {len(all_posts)}")
        return all_posts
