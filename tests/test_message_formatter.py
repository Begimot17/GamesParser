"""Tests for MessageFormatter."""


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
    game_info=None,
):
    metadata = PostMetadata(
        rating=rating,
        store_links=store_links or {},
        tags=tags or [],
        views=views,
        date=date,
        game_info=game_info or {},
    )
    return Post(id="123", title=title, link=link, content=content, metadata=metadata, source=source)


@pytest.fixture
def formatter():
    return MessageFormatter()


class TestFormatMessage:

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


class TestFormatPriceAlert:
    def test_fmt_uah_became_free(self, formatter):
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.steampowered.com/app/123/",
            old_price_uah=249900,
            new_price_uah=0,
            original_price_uah=249900,
            discount_pct=100,
            alert_type="became_free",
        )
        assert "₴2\u00a0499" in msg  # 249900 kopecks = ₴2 499
        assert "$" not in msg
        assert "Бесплатно" in msg

    def test_fmt_uah_big_discount(self, formatter):
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.steampowered.com/app/123/",
            old_price_uah=249900,
            new_price_uah=49900,
            original_price_uah=249900,
            discount_pct=80,
            alert_type="big_discount",
        )
        assert "₴2\u00a0499" in msg   # original
        assert "₴499" in msg          # final
        assert "80%" in msg
        assert "$" not in msg

    def test_short_description_included(self, formatter):
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.steampowered.com/app/123/",
            old_price_uah=249900,
            new_price_uah=49900,
            original_price_uah=249900,
            discount_pct=80,
            alert_type="big_discount",
            short_description="An amazing open-world game.",
        )
        assert "An amazing open-world game." in msg
        assert "📝" in msg

    def test_short_description_truncated(self, formatter):
        long_desc = "A" * 250
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.steampowered.com/app/123/",
            old_price_uah=100,
            new_price_uah=10,
            original_price_uah=100,
            discount_pct=90,
            alert_type="big_discount",
            short_description=long_desc,
        )
        assert "…" in msg  # truncated at 200 chars

    def test_uah_free_price_shows_bezkoshtovno(self, formatter):
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.steampowered.com/app/123/",
            old_price_uah=0,
            new_price_uah=0,
            original_price_uah=0,
            discount_pct=0,
            alert_type="big_discount",
        )
        assert "Бесплатно" in msg

    def test_cross_store_uses_uah_keys(self, formatter):
        cross = {
            "store": "steam",
            "url": "https://store.steampowered.com/app/1/",
            "price_uah": 49900,
            "original_price_uah": 249900,
            "discount_pct": 80,
        }
        msg = formatter.format_price_alert(
            name="Game",
            url="https://store.epicgames.com/en-US/p/game",
            old_price_uah=249900,
            new_price_uah=49900,
            original_price_uah=249900,
            discount_pct=80,
            alert_type="big_discount",
            store="egs",
            cross_store_data=cross,
        )
        assert "Также в Steam" in msg
        assert "₴" in msg
