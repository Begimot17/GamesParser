"""Tests for MessageFormatter."""

from datetime import datetime, timedelta, timezone

import pytest

from src.bot.message_formatter import STORE_DISPLAY_NAMES, STORE_EMOJIS, MessageFormatter
from src.models.models import Post, PostMetadata
from src.services.price_service import GameInfo


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
    def test_format_message_footer_with_source(self, formatter):
        post = make_post(source="Pikabu")
        result = formatter.format_message(post)
        assert "🤖 GamesParser | Pikabu" in result

    def test_format_message_no_source_line(self, formatter):
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
        assert "…" in result  # smart truncation uses unicode ellipsis
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


class TestTruncateContent:
    def test_truncate_short_text_unchanged(self, formatter):
        text = "Short text." * 10  # ~110 chars
        assert formatter._truncate_content(text, max_len=600) == text

    def test_truncate_at_sentence_boundary(self, formatter):
        # "." is at position 450, which is within the search range [400, 600]
        sentence = "A" * 450 + ". " + "B" * 248  # total 700 chars
        result = formatter._truncate_content(sentence, max_len=600)
        assert result.endswith("…")
        assert len(result) <= 601  # boundary + ellipsis
        # Should cut after the "." at position 450
        assert result.endswith(".…")

    def test_truncate_fallback_no_boundary(self, formatter):
        # No sentence boundary in range — hard cut
        text = "A" * 700
        result = formatter._truncate_content(text, max_len=600)
        assert result == "A" * 600 + "…"

    def test_format_message_content_truncated_smartly(self, formatter):
        # 500 A's + ". " + 300 B's → should cut after "."
        content = "A" * 498 + ". " + "B" * 300
        post = make_post(content=content)
        result = formatter.format_message(post)
        assert "B" * 50 not in result  # the B section should be cut


class TestFreeTag:
    def test_free_tag_added_when_is_free(self, formatter):
        game_info = {"steam": GameInfo(name="Free Game", is_free=True).to_dict()}
        post = make_post(store_links={"steam": "https://store.steampowered.com/app/123/"}, game_info=game_info)
        result = formatter.format_message(post)
        assert "#free" in result

    def test_free_tag_not_added_when_not_free(self, formatter):
        game_info = {"steam": GameInfo(name="Paid Game", is_free=False, price="199 ₴").to_dict()}
        post = make_post(store_links={"steam": "https://store.steampowered.com/app/123/"}, game_info=game_info)
        result = formatter.format_message(post)
        assert "#free" not in result

class TestReviewScore:
    def test_review_score_shown_in_game_info(self, formatter):
        info = GameInfo(name="Game", is_free=True, review_score="Переважно позитивні")
        line = formatter._format_game_info_line(info)
        assert "💬" in line
        assert "Переважно позитивні" in line

    def test_review_score_absent_when_none(self, formatter):
        info = GameInfo(name="Game", is_free=True, review_score=None)
        line = formatter._format_game_info_line(info)
        assert "💬" not in line

    def test_review_score_html_escaped(self, formatter):
        info = GameInfo(name="Game", is_free=True, review_score="<Good> & 'Great'")
        line = formatter._format_game_info_line(info)
        assert "&lt;Good&gt;" in line
        assert "&amp;" in line


class TestFreeTagNotDuplicated:
    def test_free_tag_not_duplicated_when_already_in_tags(self, formatter):
        game_info = {"steam": GameInfo(name="Free Game", is_free=True).to_dict()}
        post = make_post(
            store_links={"steam": "https://store.steampowered.com/app/123/"},
            game_info=game_info,
            tags=["free", "игры"],
        )
        result = formatter.format_message(post)
        assert result.count("#free") == 1


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
        assert "безкоштовною" in msg

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
        assert "Безкоштовно" in msg

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
        assert "Також у Steam" in msg
        assert "₴" in msg
