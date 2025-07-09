"""Main entry point for GamesParser project."""

import asyncio
import sys
from datetime import datetime

from common import logger
from src.bot.bot import TelegramNewsBot
from src.config.config import Config
from src.parsers.parser_manager import ParserManager
from src.storage.storage import PostStorage


class NewsMonitor:
    """Класс для мониторинга новостей и отправки их в Telegram."""

    def __init__(self):
        """Инициализация NewsMonitor."""
        logger.info("Initializing NewsMonitor...")
        if not Config.validate():
            raise ValueError(
                "Invalid configuration. Please check TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID",
            )
        self.bot = TelegramNewsBot(
            token=Config.TELEGRAM_BOT_TOKEN,
            channel_id=Config.TELEGRAM_CHANNEL_ID,
        )
        self.parser_manager = ParserManager()
        self.storage = PostStorage(db_path=Config.DB_PATH)
        logger.info("NewsMonitor initialized successfully")

    async def process_new_posts(self) -> None:
        """Обработка новых постов: фильтрация, отправка, пометка как обработанных."""
        logger.info("Starting to process new posts...")
        try:
            posts = await self.parser_manager.fetch_all_posts()
            if not posts:
                logger.info("No new posts found")
                return
            logger.info("Found %d new posts", len(posts))
            new_posts = [post for post in posts if not self.storage.is_processed(post.id)]
            new_posts.sort(
                key=lambda x: x.metadata.date
                if x.metadata and x.metadata.date
                else datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo),
            )
            for post in new_posts:
                try:
                    if self.storage.is_processed(post.id):
                        logger.info(f"Post {post.id} was already processed, skipping...")
                        continue
                    logger.info(f"Processing post {post.id}: {post.title}")
                    formatted_message = self.bot._format_message(post)
                    success = await self.bot.send_message(
                        text=formatted_message,
                        images=post.metadata.images,
                    )
                    if success:
                        self.storage.mark_as_processed(post.id)
                        logger.info(f"Successfully processed post {post.id}")
                    else:
                        logger.error(f"Failed to send post {post.id}")
                except Exception as e:
                    logger.error(f"Error processing post {post.id}: {e}")
                    continue
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in process_new_posts: {e}")

    async def run(self) -> None:
        """Запуск основного цикла мониторинга."""
        logger.info("Starting NewsMonitor...")
        try:
            while True:
                await self.process_new_posts()
                logger.info(f"Waiting {Config.CHECK_INTERVAL} seconds before next check...")
                await asyncio.sleep(Config.CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            await self.bot.close()


def main() -> None:
    """Точка входа в приложение."""
    try:
        monitor = NewsMonitor()
        asyncio.run(monitor.run())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
