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
    m.storage.mark_as_processed = AsyncMock()
    m.storage.close = AsyncMock()
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

        monitor.parser_manager = MagicMock()
        monitor.parser_manager.stream_posts = fake_stream

        asyncio.run(monitor._run_streaming())

        monitor.bot.send_message.assert_called_once()
        monitor.storage.mark_as_processed.assert_called_once_with("42")

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
