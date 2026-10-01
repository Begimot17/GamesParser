"""Tests for NewsMonitor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.models import Post, PostMetadata


def make_post(post_id="1"):
    return Post(
        id=post_id,
        title="Test Post",
        link="https://pikabu.ru/story/test_1",
        content="Content",
        metadata=PostMetadata(),
        source="Pikabu",
    )


@pytest.fixture
def monitor():
    with (
        patch("src.bot.bot.Bot"),
        patch("src.bot.bot.request.HTTPXRequest"),
        patch("main.SQLiteStorage"),
    ):
        from main import NewsMonitor
        m = NewsMonitor()
    m.bot = MagicMock()
    m.bot.formatter = MagicMock()
    m.bot.formatter.format_message = MagicMock(return_value="formatted message")
    m.bot.send_message = AsyncMock(return_value=True)
    m.storage = MagicMock()
    m.storage.is_processed = AsyncMock(return_value=False)
    m.storage.is_title_seen = AsyncMock(return_value=(False, "", ""))
    m.storage.mark_as_processed = AsyncMock()
    m.storage.mark_title_seen = AsyncMock()
    m.storage.save_failed_post = AsyncMock()
    m.storage.get_failed_posts = AsyncMock(return_value=[])
    m.storage.save_post = AsyncMock()
    m.storage.close = AsyncMock()
    m.storage.upsert_estate = AsyncMock()
    m.storage.add_post_to_estate = AsyncMock()
    m.storage.get_estate_posts = AsyncMock(return_value=[])
    m.storage.get_pending_estates = AsyncMock(return_value=[])
    m.storage.mark_estate_flushed = AsyncMock()
    m.storage.mark_posts_sent = AsyncMock()
    m.storage.save_failed_estate = AsyncMock()
    m.storage.get_failed_estates = AsyncMock(return_value=[])
    m.storage.delete_failed_estate = AsyncMock()
    m.storage.increment_estate_retry = AsyncMock()
    m.storage.delete_failed_post = AsyncMock()
    m.storage.increment_retry = AsyncMock()
    m.storage.cleanup_old_posts = AsyncMock(return_value=0)
    m.storage.init_estate_tables = AsyncMock()
    m.storage.find_matching_estate = AsyncMock(return_value=None)
    m.storage.upsert_estate = AsyncMock(return_value=False)
    m.storage.get_estates_to_edit = AsyncMock(return_value=[])
    m.storage.get_estate = AsyncMock(return_value=None)
    m.storage.clear_estate_edit = AsyncMock()
    # Storage is centralised in parser_manager now
    m.parser_manager.storage = m.storage
    return m


class TestNewsMonitorInit:
    def test_monitor_has_parsers(self, monitor):
        assert len(monitor.parsers) >= 2

    def test_monitor_parser_manager_uses_storage(self, monitor):
        """ParserManager должен использовать тот же storage, что и монитор."""
        assert monitor.parser_manager.storage is monitor.storage


class TestNewsMonitorStreaming:
    def test_run_streaming_sends_new_post(self, monitor):
        post = make_post("42")

        async def fake_stream():
            yield post
            yield None  # cycle sentinel → triggers _flush_pending_estates

        monitor.parser_manager = MagicMock()
        monitor.parser_manager.stream_posts = fake_stream

        # Simulate one pending estate that should be flushed
        pending_estate = {
            "estate_id": "abc123",
            "title": "Test Post",
            "store_url": None,
            "store_name": None,
            "is_free": False,
            "description": "Content",
            "posts": [{"source": "Pikabu", "post_link": "https://pikabu.ru/story/test_1"}],
            "tags": [],
            "images": [],
        }
        monitor.storage.get_pending_estates = AsyncMock(return_value=[pending_estate])
        monitor.bot.formatter.format_estate_alert = MagicMock(return_value="formatted estate")

        asyncio.run(monitor._run_streaming())

        monitor.bot.send_message.assert_called_once()
        monitor.storage.mark_estate_flushed.assert_called_once()

    def test_run_streaming_skips_processed(self, monitor):
        post = make_post("99")
        monitor.storage.is_processed = AsyncMock(return_value=True)

        async def fake_stream():
            yield post

        monitor.parser_manager = MagicMock()
        monitor.parser_manager.stream_posts = fake_stream

        asyncio.run(monitor._run_streaming())

        monitor.bot.send_message.assert_not_called()
        monitor.storage.mark_as_processed.assert_not_called()
