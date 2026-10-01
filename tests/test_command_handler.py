"""Tests for CommandHandler bot commands."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.command_handler import CommandHandler


def make_update(user_id: int = 999):
    """Create a minimal mock Update object."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    return MagicMock()


class TestCommandHandlerStats(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MagicMock()
        self.storage.get_posts_stats = AsyncMock(return_value={
            "total": 42,
            "sent": 38,
            "is_free": 10,
            "by_source": {"VGTimes": 20, "Pikabu": 22},
        })
        self.monitor = MagicMock()
        self.handler = CommandHandler(self.storage, self.monitor)

    @patch("src.bot.command_handler.settings")
    async def test_cmd_stats_replies_with_numbers(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = []
        update = make_update()

        await self.handler.cmd_stats(update, make_context())

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "42" in text
        assert "38" in text
        assert "VGTimes" in text

    @patch("src.bot.command_handler.settings")
    async def test_cmd_stats_blocked_for_non_admin(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = [111, 222]
        update = make_update(user_id=999)

        await self.handler.cmd_stats(update, make_context())

        update.message.reply_text.assert_not_called()


class TestCommandHandlerRecent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MagicMock()
        self.storage.get_recent_posts = AsyncMock(return_value=[
            {"id": "1", "source": "VGTimes", "title": "Test Game", "link": "https://vgtimes.ru/1", "sent_at": "2026-03-14"},
        ])
        self.monitor = MagicMock()
        self.handler = CommandHandler(self.storage, self.monitor)

    @patch("src.bot.command_handler.settings")
    async def test_cmd_recent_replies_with_post(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = []
        update = make_update()

        await self.handler.cmd_recent(update, make_context())

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Test Game" in text
        assert "VGTimes" in text

    @patch("src.bot.command_handler.settings")
    async def test_cmd_recent_empty_dlq(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = []
        self.storage.get_recent_posts = AsyncMock(return_value=[])
        update = make_update()

        await self.handler.cmd_recent(update, make_context())

        text = update.message.reply_text.call_args[0][0]
        assert "немає" in text.lower() or "нет" in text.lower() or "empty" in text.lower() or "постів" in text


class TestCommandHandlerRetry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MagicMock()
        self.storage.get_failed_estates = AsyncMock(return_value=[{"estate_id": "e1"}])
        self.monitor = MagicMock()
        self.monitor._retry_failed_estates = AsyncMock()
        self.handler = CommandHandler(self.storage, self.monitor)

    @patch("src.bot.command_handler.settings")
    async def test_cmd_retry_triggers_dlq(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = []
        update = make_update()

        await self.handler.cmd_retry(update, make_context())

        self.monitor._retry_failed_estates.assert_called_once()
        assert update.message.reply_text.call_count == 2  # "Повторная попытка…" + "✅ Повтор завершён."

    @patch("src.bot.command_handler.settings")
    async def test_cmd_retry_empty_dlq(self, mock_settings):
        mock_settings.ADMIN_USER_IDS = []
        self.storage.get_failed_estates = AsyncMock(return_value=[])
        update = make_update()

        await self.handler.cmd_retry(update, make_context())

        self.monitor._retry_failed_estates.assert_not_called()
        text = update.message.reply_text.call_args[0][0]
        assert "пуста" in text or "empty" in text.lower()


if __name__ == "__main__":
    unittest.main()
