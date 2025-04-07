import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Set

from bot.bot import TelegramNewsBot
from config.config import Config
from models.models import Post
from parser.parser import Parser
from storage.storage import PostStorage

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


class NewsMonitor:
    def __init__(self):
        logger.info("Initializing NewsMonitor...")
        
        # Validate configuration
        if not Config.validate():
            raise ValueError("Invalid configuration. Please check TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID")
            
        # Initialize components
        self.bot = TelegramNewsBot(
            token=Config.TELEGRAM_BOT_TOKEN,
            channel_id=Config.TELEGRAM_CHANNEL_ID
        )
        self.parser = Parser()
        self.storage = PostStorage()
        
        logger.info("NewsMonitor initialized successfully")

    async def cleanup_old_posts(self):
        """Удаление старых постов из памяти."""
        logger.info("Cleaning up old posts from memory...")
        self.storage.cleanup_old_posts()
        logger.info(f"Cleanup completed. Current processed posts count: {len(self.storage.processed_posts)}")

    async def process_new_posts(self):
        """Обработка новых постов."""
        logger.info("Starting to process new posts...")
        
        try:
            # Получаем новые посты
            posts = await self.parser.fetch_posts()
            if not posts:
                logger.info("No new posts found")
                return
                
            logger.info(f"Found {len(posts)} new posts")
            
            # Фильтруем уже обработанные посты
            new_posts = [post for post in posts if not self.storage.is_processed(post.id)]
            
            # Обрабатываем новые посты
            for post in new_posts:
                try:
                    # Проверяем, не был ли пост уже отправлен
                    if self.storage.is_processed(post.id):
                        logger.info(f"Post {post.id} was already processed, skipping...")
                        continue
                        
                    logger.info(f"Processing post {post.id}: {post.title}")
                    
                    # Форматируем сообщение
                    formatted_message = self.bot._format_message(post)
                    
                    # Отправляем сообщение
                    success = await self.bot.send_message(
                        text=formatted_message,
                        images=post.images
                    )
                    
                    if success:
                        # Помечаем пост как обработанный
                        self.storage.mark_as_processed(post.id)
                        logger.info(f"Successfully processed post {post.id}")
                    # Ждем перед следующей попыткой
                    else:
                        logger.error(f"Failed to send post {post.id}")
                        
                except Exception as e:
                    logger.error(f"Error processing post {post.id}: {str(e)}")
                    continue
                await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"Error in process_new_posts: {str(e)}")

    async def run(self):
        """Запуск монитора."""
        logger.info("Starting NewsMonitor...")
        
        try:
            while True:
                await self.process_new_posts()
                await self.cleanup_old_posts()
                
                logger.info(f"Waiting {Config.CHECK_INTERVAL} seconds before next check...")
                await asyncio.sleep(Config.CHECK_INTERVAL)
                
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
        finally:
            await self.bot.close()


async def main():
    """Основная функция."""
    try:
        monitor = NewsMonitor()
        await monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 