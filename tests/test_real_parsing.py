"""
Real parsing integration tests.

Запускает реальный парсинг Pikabu и VGTimes, отправляет посты в TEST_CHANNEL_ID.
Использует TEST_DB_PATH чтобы не трогать основную БД.

Run:
    pytest tests/test_real_parsing.py -v -s
"""

import asyncio

import pytest

from src.bot.bot import TelegramNewsBot
from src.config.config import settings
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.storage.sqlite_storage import SQLiteStorage


pytestmark = pytest.mark.skipif(
    not settings.TEST_CHANNEL_ID,
    reason="TEST_CHANNEL_ID not set in .env",
)

MAX_POSTS_PER_PARSER = 3  # сколько постов отправить с каждого источника


async def run_parser_and_send(parser, bot: TelegramNewsBot, storage: SQLiteStorage, limit: int) -> int:
    """Запускает stream_posts парсера, отправляет до limit постов в канал."""
    sent = 0
    async for post in parser.stream_posts():
        if sent >= limit:
            break
        if await storage.is_processed(post.id):
            continue

        message = bot.formatter.format_message(post)
        images = post.metadata.images if post.metadata and post.metadata.images else None
        success = await bot.send_message(message, images=images)

        if success:
            await storage.mark_as_processed(post.id)
            print(f"  OK [{post.source}] {post.title[:60]}")
            sent += 1
        else:
            print(f"  FAIL: {post.title[:60]}")

        await asyncio.sleep(2)  # пауза между постами

    return sent


class TestRealParsing:
    def test_pikabu_parse_and_send(self, cleanup_test_db):
        """Парсит реальные посты с Pikabu и отправляет в тестовый канал."""
        async def run():
            storage = SQLiteStorage(settings.TEST_DB_PATH)
            bot = TelegramNewsBot(
                token=settings.TELEGRAM_BOT_TOKEN,
                channel_id=settings.TEST_CHANNEL_ID,
            )
            parser = PikabuParser()
            try:
                print(f"\nПарсим Pikabu -> {settings.TEST_CHANNEL_ID}")
                sent = await run_parser_and_send(parser, bot, storage, MAX_POSTS_PER_PARSER)
                print(f"Отправлено постов: {sent}")
                return sent
            finally:
                if parser.session and not parser.session.closed:
                    await parser.session.close()
                await storage.close()
                await bot.close()

        sent = asyncio.run(run())
        assert sent > 0, "Ни одного поста не отправлено с Pikabu"

    def test_vgtimes_parse_and_send(self, cleanup_test_db):
        """Парсит реальные посты с VGTimes и отправляет в тестовый канал."""
        async def run():
            storage = SQLiteStorage(settings.TEST_DB_PATH)
            bot = TelegramNewsBot(
                token=settings.TELEGRAM_BOT_TOKEN,
                channel_id=settings.TEST_CHANNEL_ID,
            )
            parser = VGTimesParser()
            try:
                print(f"\nПарсим VGTimes -> {settings.TEST_CHANNEL_ID}")
                sent = await run_parser_and_send(parser, bot, storage, MAX_POSTS_PER_PARSER)
                print(f"Отправлено постов: {sent}")
                return sent
            finally:
                if parser.session and not parser.session.closed:
                    await parser.session.close()
                await storage.close()
                await bot.close()

        sent = asyncio.run(run())
        assert sent > 0, "Ни одного поста не отправлено с VGTimes"
