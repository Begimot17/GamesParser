"""Parser manager for GamesParser project."""
import asyncio
from typing import List

from src.common.logger import logger
from src.config.config import Config


class ParserManager:
    """Manages parsing operations across multiple sources."""

    def __init__(self, parsers: List):
        logger.info("[ParserManager] Initializing parser manager...")
        self.parsers = parsers
        logger.info(
            f"[ParserManager] Parsers initialized: {[type(p).__name__ for p in self.parsers]}"
        )

    async def fetch_all_posts(self) -> list:
        """Fetches posts from all configured parsers."""
        logger.info("[ParserManager] Fetching posts from all parsers...")
        all_posts: list = []
        for parser in self.parsers:
            logger.info(f"[ParserManager] Fetching posts using {type(parser).__name__}")
            try:
                async with parser:
                    posts = await parser.fetch_posts()
                    logger.info(
                        f"[ParserManager] {type(parser).__name__} returned {len(posts)} posts"
                    )
                    all_posts.extend(posts)
            except Exception as e:
                logger.error(
                    f"[ParserManager] Error fetching posts from {type(parser).__name__}: {e}",
                    exc_info=True,
                )
                return []
        logger.info(f"[ParserManager] Total posts fetched: {len(all_posts)}")
        return all_posts

    async def stream_posts(self):
        """Infinite generator for streaming posts."""
        logger.info(
            "[ParserManager] Starting infinite streaming of posts from all parsers..."
        )
        while True:
            for parser in self.parsers:
                logger.info(
                    f"[ParserManager] Streaming posts using {type(parser).__name__}"
                )
                try:
                    async with parser:
                        async for post in parser.stream_posts():
                            if post:
                                logger.info(
                                    f"[ParserManager] Yielding post {post.id} from {type(parser).__name__}"
                                )
                                yield post
                            else:
                                logger.warning(
                                    f"[ParserManager] Received empty post from {type(parser).__name__}"
                                )
                except Exception as e:
                    logger.error(
                        f"[ParserManager] Error streaming posts from {type(parser).__name__}: {e}",
                        exc_info=True,
                    )
                    continue

            logger.info(
                f"All parsers have been checked. Waiting {Config.STREAMING_CYCLE_DELAY} seconds before next cycle..."
            )
            await asyncio.sleep(Config.STREAMING_CYCLE_DELAY)
