"""
Real integration tests for TelegramNewsBot.

Sends actual messages to TEST_CHANNEL_ID (from .env).
Requires TEST_CHANNEL_ID and TELEGRAM_BOT_TOKEN to be set.

Run:
    pytest tests/test_integration_bot.py -v -s
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.bot.bot import TelegramNewsBot
from src.config.config import settings
from src.models.models import Post, PostMetadata
from src.storage import game_keys


# Skip all tests if TEST_CHANNEL_ID is not configured
pytestmark = pytest.mark.skipif(
    not settings.TEST_CHANNEL_ID,
    reason="TEST_CHANNEL_ID not set in .env — skipping real Telegram tests",
)


def make_bot() -> TelegramNewsBot:
    return TelegramNewsBot(
        token=settings.TELEGRAM_BOT_TOKEN,
        channel_id=settings.TEST_CHANNEL_ID,
    )


def make_post(
    title="[TEST] GamesParser Integration Test",
    content="Это тестовое сообщение от GamesParser. Можно игнорировать.",
    source="Pikabu",
    rating=42,
    views="1.2K",
    tags=["тест", "games parser", "интеграция"],
    store_links=None,
    images=None,
    date=None,
) -> Post:
    if date is None:
        date = datetime.now(timezone(timedelta(hours=3)))
    metadata = PostMetadata(
        rating=rating,
        views=views,
        tags=tags,
        store_links=store_links or {},
        images=images or [],
        date=date,
    )
    return Post(
        id="integration_test_001",
        title=title,
        link="https://pikabu.ru/story/integration_test_001",
        content=content,
        metadata=metadata,
        source=source,
    )


async def send_post(bot: TelegramNewsBot, post: Post) -> bool:
    """Вспомогательная функция: форматирует и отправляет пост, затем закрывает бота."""
    message = bot.formatter.format_estate_alert(game_keys.estate_from_post(post))
    images = post.metadata.images if post.metadata.images else None
    result = await bot.send_message(message, images=images)
    await bot.close()
    return result


class TestRealTelegramSend:
    def test_send_text_post_pikabu(self):
        """Отправляет форматированный пост Pikabu в тестовый канал."""
        bot = make_bot()
        post = make_post(source="Pikabu")
        result = asyncio.run(send_post(bot, post))
        assert result, "Сообщение не отправлено"

    def test_send_text_post_vgtimes(self):
        """Отправляет форматированный пост VGTimes в тестовый канал."""
        bot = make_bot()
        post = make_post(
            title="[TEST] VGTimes — Бесплатная игра недели",
            content="The Forgotten City теперь бесплатна в Epic Games Store. Детективная RPG с механикой временной петли.",
            source="VGTimes",
            store_links={
                "steam": "https://store.steampowered.com/app/874260/",
                "epicgames": "https://epicgames.com/p/the-forgotten-city",
            },
            tags=[],
        )
        result = asyncio.run(send_post(bot, post))
        assert result, "Сообщение не отправлено"

    def test_send_text_post_stopgame(self):
        """Отправляет форматированный пост StopGame в тестовый канал."""
        bot = make_bot()
        post = make_post(
            title="[TEST] StopGame — Обзор новой игры",
            content="StopGame тестирует интеграцию с GamesParser. Контент загружается с полной страницы статьи.",
            source="StopGame",
            tags=["обзор", "новинки"],
        )
        result = asyncio.run(send_post(bot, post))
        assert result, "Сообщение не отправлено"

    def test_send_post_with_image(self):
        """Отправляет пост с изображением в тестовый канал."""
        bot = make_bot()
        post = make_post(
            title="[TEST] Пост с изображением",
            content="Проверка отправки медиагруппы с изображением.",
            source="Pikabu",
            # Используем публично доступное изображение
            images=["https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/640px-Camponotus_flavomarginatus_ant.jpg"],
        )
        result = asyncio.run(send_post(bot, post))
        assert result, "Сообщение с изображением не отправлено"

    def test_send_post_with_store_links(self):
        """Отправляет пост со ссылками на магазины."""
        bot = make_bot()
        post = make_post(
            title="[TEST] Пост со ссылками на магазины",
            content="Проверка форматирования ссылок на Steam, Epic Games и GOG с эмодзи.",
            source="VGTimes",
            store_links={
                "steam": "https://store.steampowered.com/app/292030/",
                "gog": "https://www.gog.com/game/the_witcher_3_wild_hunt",
            },
            tags=["witcher", "RPG"],
        )
        result = asyncio.run(send_post(bot, post))
        assert result, "Сообщение со ссылками не отправлено"
