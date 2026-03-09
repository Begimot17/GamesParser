import asyncio
import logging
import sys
from typing import List

from src.bot.bot import TelegramNewsBot
from src.common.logger import setup_logger, logger
from src.config.config import settings
from src.parsers.parser_manager import ParserManager
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.stopgame_parser import StopGameParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.storage.sqlite_storage import SQLiteStorage


class NewsMonitor:
    """Main class for monitoring news sources."""

    def __init__(self):
        self.settings = settings
        
        self.storage = SQLiteStorage(self.settings.DB_PATH)
        self.bot = TelegramNewsBot(
            token=self.settings.TELEGRAM_BOT_TOKEN,
            channel_id=self.settings.TELEGRAM_CHANNEL_ID
        )

        # Initialize parsers with shared storage
        self.parsers = [
            PikabuParser(storage=self.storage),
            VGTimesParser(storage=self.storage),
            StopGameParser(storage=self.storage),
        ]
        self.parser_manager = ParserManager(self.parsers)

    async def run(self, use_streaming: bool = True):
        """Runs the monitoring loop."""
        logger.info("Starting NewsMonitor...")
        try:
            if use_streaming:
                await self._run_streaming()
            else:
                await self._run_polling()
        except KeyboardInterrupt:
            logger.info("NewsMonitor stopped by user.")
        finally:
            await self.storage.close()
            await self.bot.close()

    async def _run_streaming(self):
        """Runs the monitoring loop using streaming."""
        logger.info("Starting streaming mode...")
        async for post in self.parser_manager.stream_posts():
            try:
                if await self.storage.is_processed(post.id):
                    continue

                logger.info(f"New post found: {post.title} ({post.link})")
                success = await self.bot.send_message(
                    self.bot.formatter.format_message(post),
                    images=post.metadata.images if post.metadata else None
                )
                
                if success:
                    await self.storage.mark_as_processed(post.id)
                    logger.info(f"Post {post.id} processed and sent.")
                else:
                    logger.error(f"Failed to send post {post.id}")
                
                await asyncio.sleep(self.settings.STREAM_POST_PROCESSING_DELAY)

            except Exception as e:
                logger.error(f"Error processing post in stream: {e}", exc_info=True)

    async def _run_polling(self):
        """Runs the monitoring loop using polling (legacy)."""
        logger.info("Starting polling mode...")
        while True:
            try:
                 posts = await self.parser_manager.fetch_all_posts()
                 for post in posts:
                    if await self.storage.is_processed(post.id):
                        continue

                    logger.info(f"New post found: {post.title}")
                    success = await self.bot.send_message(
                        self.bot.formatter.format_message(post),
                        images=post.metadata.images if post.metadata else None
                    )

                    if success:
                        await self.storage.mark_as_processed(post.id)
                    
                    await asyncio.sleep(self.settings.POST_PROCESSING_DELAY)
                 
                 logger.info(f"Sleeping for {self.settings.CHECK_INTERVAL} seconds...")
                 await asyncio.sleep(self.settings.CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(self.settings.CHECK_INTERVAL)


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
