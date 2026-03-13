"""Tests for MessageFormatter."""

from datetime import datetime, timedelta, timezone

import pytest

from src.bot.message_formatter import STORE_DISPLAY_NAMES, STORE_EMOJIS, MessageFormatter
from src.models.models import Post, PostMetadata


def make_post(
    title="Test Game",
    link="https://pikabu.ru/story/test_123",
    content="Some content here.",
    source="Pikabu",
    rating=None,
    store_links=None,
    tags=None,
    views=None,
    date=None,
):
    metadata = PostMetadata(
        rating=rating,
        store_links=store_links or {},
        tags=tags or [],
        views=views,
        date=date,
    )
    return Post(id="123", title=title, link=link, content=content, metadata=metadata, source=source)


@pytest.fixture
def formatter():
    return MessageFormatter()


class TestFormatMessage:
    def test_format_message_with_source(self, formatter):
        post = make_post(source="Pikabu")
        result = formatter.format_message(post)
        assert "<i>Источник: Pikabu</i>" in result

    def test_format_message_no_source(self, formatter):
        post = make_post(source=None)
        result = formatter.format_message(post)
        assert "Источник:" not in result

    def test_format_message_store_links_with_emojis(self, formatter):
        post = make_post(store_links={
            "steam": "https://store.steampowered.com/app/123/",
            "epicgames": "https://epicgames.com/p/game",
        })
        result = formatter.format_message(post)
        assert "🎮" in result
        assert "Steam" in result
        assert "🟣" in result
        assert "Epic Games" in result

    def test_format_message_russian_tags(self, formatter):
        post = make_post(tags=["игры", "скидки steam", "новинки"])
        result = formatter.format_message(post)
        assert "#игры" in result
        assert "#скидки_steam" in result
        assert "#новинки" in result

    def test_format_message_content_truncation(self, formatter):
        long_content = "А" * 700
        post = make_post(content=long_content)
        result = formatter.format_message(post)
        assert "..." in result
        # Content section should not exceed 600 chars + "..."
        assert len(result) < 5000  # sanity check

    def test_format_message_html_escaping(self, formatter):
        post = make_post(title="Game <Title> & More", content="Content with <b>bold</b> & stuff")
        result = formatter.format_message(post)
        assert "&lt;Title&gt;" in result
        assert "&amp;" in result

    def test_format_message_title_link(self, formatter):
        post = make_post(title="My Game", link="https://pikabu.ru/story/test_123")
        result = formatter.format_message(post)
        assert "https://pikabu.ru/story/test_123" in result
        assert "My Game" in result

    def test_format_date(self, formatter):
        dt = datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)
        assert formatter.format_date(dt) == "09.03.2026 14:30"

    def test_format_date_none(self, formatter):
        assert formatter.format_date(None) is None

    def test_format_message_with_meta(self, formatter):
        dt = datetime(2026, 3, 9, 14, 30, tzinfo=timezone(timedelta(hours=3)))
        post = make_post(rating=150, views="45K", date=dt)
        result = formatter.format_message(post)
        assert "⭐ 150" in result
        assert "👁 45K" in result
        assert "📅" in result

    def test_clean_url_strips_query(self, formatter):
        url = "https://store.steampowered.com/app/123/?snr=abc"
        result = formatter.clean_url(url)
        assert result == "https://store.steampowered.com/app/123/"

    def test_to_plain_text(self, formatter):
        html_text = "<b>Hello</b> &amp; <i>World</i>"
        result = formatter.to_plain_text(html_text)
        assert result == "Hello & World"

    def test_store_display_names_mapping(self, formatter):
        assert STORE_DISPLAY_NAMES["steam"] == "Steam"
        assert STORE_DISPLAY_NAMES["epicgames"] == "Epic Games"
        assert STORE_DISPLAY_NAMES["gog"] == "GOG"

    def test_store_emojis_mapping(self, formatter):
        assert STORE_EMOJIS["steam"] == "🎮"
        assert STORE_EMOJIS["epicgames"] == "🟣"
