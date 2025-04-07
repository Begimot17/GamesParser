import asyncio
import logging
from src.parser.vgtimes_parser import VGTimesParser

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    parser = VGTimesParser()
    posts = await parser.fetch_posts()
    if not posts:
        logger.error("Не удалось получить посты")
    else:
        for post in posts:
            logger.info(f"ID: {post.id}")
            logger.info(f"Title: {post.title}")
            logger.info(f"Link: {post.link}")
            logger.info(f"Content: {post.content[:200] + '...' if post.content else None}")
            logger.info(f"Image: {post.image_url}")
            if post.metadata:
                logger.info(f"Rating: {post.metadata.rating}")
                logger.info(f"Date: {post.metadata.date}")
                if post.metadata.store_links:
                    logger.info(f"Store Links: {post.metadata.store_links}")
                if post.metadata.images:
                    logger.info(f"All Images: {post.metadata.images}")
            logger.info("---")

if __name__ == "__main__":
    asyncio.run(main()) 