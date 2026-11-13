"""Parser manager for GamesParser project."""
import asyncio
from typing import AsyncGenerator, Optional

from src.common.logger import logger
from src.config.config import settings
from src.models.models import Post
from src.parsers.utils.base_parser import BaseParser
from src.storage.base import Storage


class ParserManager:
    """Manages parsing operations across multiple sources."""

    def __init__(self, parsers: list[BaseParser], storage: Optional[Storage] = None):
        logger.info("[ParserManager] Initializing parser manager...")
        self.parsers = parsers
        self.storage = storage
        logger.info(
            f"[ParserManager] Parsers initialized: {[type(p).__name__ for p in self.parsers]}",
        )

    async def _get_is_first_run(self) -> bool:
        """Returns True if the posts table is empty (first run)."""
        if not self.storage:
            return False
        try:
            stats = await self.storage.get_posts_stats()
            return stats.get("total", 0) == 0
        except Exception as e:
            logger.warning("[ParserManager] Cannot read posts stats, assuming not first run: %s", e)
            return False

    async def stream_posts(self) -> AsyncGenerator[Optional[Post], None]:
        """Infinite generator for streaming posts. Yields None as a cycle sentinel after all parsers complete."""
        logger.info(
            "[ParserManager] Starting infinite streaming of posts from all parsers...",
        )
        while True:
            is_first_run = await self._get_is_first_run()
            for parser in self.parsers:
                parser._is_first_run = is_first_run
                parser.is_known = self.storage.is_processed if self.storage else None
                logger.info(
                    f"[ParserManager] Streaming posts using {type(parser).__name__}"
                    + (" (first run)" if is_first_run else ""),
                )
                try:
                    async with parser:
                        async for post in parser.stream_posts():
                            if not post:
                                logger.warning(
                                    f"[ParserManager] Received empty post from {type(parser).__name__}",
                                )
                                continue
                            if self.storage and await self.storage.is_processed(post.id):
                                logger.debug(
                                    f"[ParserManager] Post {post.id} already processed, skipping",
                                )
                                continue
                            logger.info(
                                f"[ParserManager] Yielding post {post.id} from {type(parser).__name__}",
                            )
                            yield post
                except Exception as e:
                    logger.error(
                        f"[ParserManager] Error streaming posts from {type(parser).__name__}: {e}",
                        exc_info=True,
                    )
                    continue

            logger.info("[ParserManager] All parsers done — yielding cycle sentinel")
            yield None  # cycle sentinel: signals end of one full scan
            logger.info(
                f"All parsers have been checked. Waiting {settings.STREAMING_CYCLE_DELAY} seconds before next cycle...",
            )
            await asyncio.sleep(settings.STREAMING_CYCLE_DELAY)
