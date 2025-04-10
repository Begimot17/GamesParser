import asyncio
import logging
import os
import sys
from datetime import datetime

# Добавляем путь к корневой директории проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.parser.dtf_parser import DTFParser
from src.parser.vgtimes_parser import VGTimesParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_parser(parser_class, parser_name: str):
    """Тестирование парсера"""
    logger.info(f"Testing {parser_name} parser...")

    try:
        async with parser_class() as parser:
            posts = await parser.fetch_posts()

            if not posts:
                logger.warning(f"No posts found from {parser_name}")
                return

            logger.info(f"Found {len(posts)} posts from {parser_name}")

            # Проверяем каждый пост
            for i, post in enumerate(posts, 1):
                logger.info(f"\nPost {i} from {parser_name}:")
                logger.info(f"ID: {post.id}")
                logger.info(f"Title: {post.title}")
                logger.info(f"Link: {post.link}")
                logger.info(f"Date: {post.date}")
                logger.info(f"Content length: {len(post.content)}")
                logger.info(f"Rating: {post.metadata.rating}")
                logger.info(f"Store links: {post.metadata.store_links}")
                logger.info(f"Images count: {len(post.metadata.images)}")

                # Проверяем обязательные поля
                assert post.id, f"Post {i} has no ID"
                assert post.title, f"Post {i} has no title"
                assert post.link, f"Post {i} has no link"
                assert isinstance(post.date, datetime) or post.date is None, (
                    f"Post {i} has invalid date"
                )
                assert isinstance(post.metadata.rating, str), (
                    f"Post {i} has invalid rating"
                )
                assert isinstance(post.metadata.store_links, dict), (
                    f"Post {i} has invalid store links"
                )
                assert isinstance(post.metadata.images, list), (
                    f"Post {i} has invalid images"
                )

                # Проверяем URL изображений
                for img_url in post.metadata.images:
                    assert img_url.startswith("http"), (
                        f"Invalid image URL in post {i}: {img_url}"
                    )

                # Проверяем URL магазинов
                for store, url in post.metadata.store_links.items():
                    assert url.startswith("http"), (
                        f"Invalid store URL in post {i}: {url}"
                    )

            logger.info(f"{parser_name} parser test completed successfully")

    except Exception as e:
        logger.error(f"Error testing {parser_name} parser: {str(e)}", exc_info=True)


async def main():
    """Основная функция тестирования"""
    try:
        # Тестируем оба парсера
        await test_parser(DTFParser, "DTF")
        await test_parser(VGTimesParser, "VGTimes")

    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
