"""Main entry point for GamesParser project."""

import asyncio
import sys
from datetime import datetime

from telegram.error import NetworkError, RetryAfter, TimedOut

from src.bot.bot import TelegramNewsBot
from src.common.logger import logger
from src.config.config import Config
from src.parsers.parser_manager import ParserManager
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.stopgame_parser import StopGameParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.storage.storage import JsonStorage


class NewsMonitor:
    """Class for monitoring news and sending them to Telegram."""

    def __init__(self):
        logger.info("Initializing NewsMonitor...")
        if not Config.validate():
            raise ValueError(
                "Invalid configuration. Please check TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID",
            )
        self.bot = TelegramNewsBot(
            token=Config.TELEGRAM_BOT_TOKEN,
            channel_id=Config.TELEGRAM_CHANNEL_ID,
        )
        self.parsers = [VGTimesParser(), PikabuParser(), StopGameParser()]
        self.parser_manager = ParserManager(parsers=self.parsers)
        self.storage = JsonStorage(db_path=Config.DB_PATH)
        logger.info("NewsMonitor initialized successfully")

    async def _process_and_send_post(self, post) -> bool:
        """
        Processes and sends a single post.
        Handles formatting, sending, and marking as processed.
        """
        post_id = getattr(post, "id", "unknown")
        try:
            logger.info(f"Processing post {post_id}: {post.title}")

            if hasattr(post, "metadata") and post.metadata:
                images = getattr(post.metadata, "images", [])
            else:
                images = []

            formatted_message = self.bot._format_message(post)
            success = await self.bot.send_message(
                text=formatted_message,
                images=images,
            )

            if success:
                self.storage.mark_as_processed(post.id)
                logger.info(f"Successfully processed and sent post {post.id}")
            else:
                logger.error(f"Failed to send post {post_id} after multiple retries.")

            return success
        except (TimedOut, NetworkError) as e:
            logger.error(
                f"Network error while sending post {post_id}: {e}. Will retry later."
            )
            return False
        except RetryAfter as e:
            logger.warning(
                f"Rate limit hit for post {post_id}. Waiting {e.retry_after} seconds."
            )
            await asyncio.sleep(e.retry_after)
            return False
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while processing post {post_id}: {e}",
                exc_info=True,
            )
            return False

    async def process_new_posts(self) -> None:
        """Fetch, filter, and process new posts."""
        logger.info("Starting to process new posts...")
        try:
            posts = await self.parser_manager.fetch_all_posts()
            if not posts:
                logger.info("No new posts found")
                return
            logger.info("Found %d posts", len(posts))

            new_posts = [
                post for post in posts if not self.storage.is_processed(post.id)
            ]
            logger.info("After additional filtering: %d new posts", len(new_posts))

            new_posts.sort(
                key=lambda x: x.metadata.date
                if x.metadata and x.metadata.date
                else datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo),
            )

            for post in new_posts:
                await self._process_and_send_post(post)
                await asyncio.sleep(Config.POST_PROCESSING_DELAY)
        except Exception as e:
            logger.error(f"Error in process_new_posts: {e}", exc_info=True)

    async def stream_and_process_posts(self) -> None:
        """Stream posts and process them as they arrive."""
        logger.info("Starting stream processing of posts...")
        try:
            async for post in self.parser_manager.stream_posts():
                if self.storage.is_processed(post.id):
                    logger.info(f"Post {post.id} already processed, skipping...")
                    continue

                await self._process_and_send_post(post)
                await asyncio.sleep(Config.STREAM_POST_PROCESSING_DELAY)

        except Exception as e:
            logger.error(f"Error in stream_and_process_posts: {e}", exc_info=True)

    async def run(self, use_streaming: bool = True) -> None:
        """Run the main monitoring loop."""
        logger.info(
            f"Starting NewsMonitor in {'streaming' if use_streaming else 'batch'} mode..."
        )
        try:
            if use_streaming:
                await self.stream_and_process_posts()
            else:
                while True:
                    await self.process_new_posts()
                    logger.info(
                        f"Waiting {Config.CHECK_INTERVAL} seconds before next check..."
                    )
                    await asyncio.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            await self.bot.close()
            self.storage.close()


def main() -> None:
    """Entry point."""
    try:
        monitor = NewsMonitor()
        asyncio.run(monitor.run(use_streaming=True))
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
