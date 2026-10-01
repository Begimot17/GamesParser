"""Cross-source grouping of posts into estates (one message per game event)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.bot import SentMessage
from src.bot.message_formatter import MessageFormatter
from src.models.models import Post, PostMetadata
from src.storage import game_keys
from src.storage.sqlite_storage import SQLiteStorage


def make_post(post_id, title, source, content="", store_links=None, game_info=None):
    return Post(
        id=post_id, title=title, link=f"https://example.com/{source.lower()}/{post_id}", content=content,
        source=source, metadata=PostMetadata(store_links=store_links or {}, game_info=game_info or {}),
    )


# ── game_keys ─────────────────────────────────────────────────────────────

class TestGameKeys:
    @pytest.mark.parametrize("title, expected", [
        ("Халява: в Steam началась бесплатная раздача хоррор-шутера Deadshot", ["Deadshot"]),
        ("Deadshot — 100% скидка в STEAM!", ["Deadshot"]),
        ("Халява: на PC началась бесплатная раздача двух игр — Mechabellum и Astrea: Six-Sided Oracles",
         ["Mechabellum", "Astrea: Six-Sided Oracles"]),
        ("For Honor - 100% скидка в Ubisoft Connect!", ["For Honor"]),
        ("В Steam навсегда бесплатно отдают сразу 7 игр — среди них космическая RPG", []),
    ])
    def test_names_from_title(self, title, expected):
        assert game_keys.names_from_title(title) == expected

    def test_store_keys_ignore_egs_hash_suffix(self):
        assert game_keys.store_key("epicgames", "https://store.epicgames.com/p/mechabellum-88a843") == "egs:mechabellum"
        assert game_keys.store_key("steam", "https://store.steampowered.com/app/669330/Mechabellum/") == "steam:669330"

    def test_same_game_in_two_stores_is_one_game(self):
        games = game_keys.games_from_links({
            "steam": ["https://store.steampowered.com/app/669330/Mechabellum/"],
            "epicgames": ["https://store.epicgames.com/p/mechabellum-88a843"],
        })
        assert len(games) == 1
        assert set(games[0]["links"]) == {"steam", "epicgames"}

    def test_event_kind_separates_mobile(self):
        assert game_keys.event_kind(True, "На Android и iOS бесплатно отдают Mindcop") == "free:mobile"
        assert game_keys.event_kind(True, "Mindcop — 100% скидка в Epic Games Store!") == "free:pc"
        assert game_keys.event_kind(True, "Ubisoft Studios giveaway") == "free:pc"


# ── storage matching ──────────────────────────────────────────────────────

@pytest.fixture
def storage(tmp_path):
    s = SQLiteStorage(str(tmp_path / "estates.db"))
    yield s
    asyncio.run(s.close())


def _add(storage, estate_id, post, sent=False):
    async def run():
        games = game_keys.games_from_links(post.metadata.store_links, post.metadata.game_info)
        kind = game_keys.event_kind(True, post.title)
        keys = game_keys.estate_keys(post.title, games)
        found = await storage.find_matching_estate(keys, post.title, kind)
        target = found or estate_id
        already_sent = await storage.upsert_estate(
            target, post.title, kind=kind, is_free=True, description=post.content, source=post.source,
            games=games, keys=keys,
        )
        await storage.add_post_to_estate(target, post)
        if sent:
            await storage.mark_estate_flushed(target, sent=True, message_id=777, is_caption=True)
        return target, already_sent
    return asyncio.run(run())


class TestEstateMatching:
    def test_matches_by_store_link(self, storage):
        steam = {"steam": ["https://store.steampowered.com/app/2484180/Deadshot/"]}
        a, _ = _add(storage, "a", make_post("1", "Deadshot — 100% скидка в STEAM!", "Pikabu", store_links=steam))
        b, _ = _add(storage, "b", make_post("2", "Раздача шутера", "VGTimes", store_links=steam))
        assert a == b == "a"

    def test_matches_by_name_in_headline_without_links(self, storage):
        links = {
            "steam": ["https://store.steampowered.com/app/669330/Mechabellum/"],
            "epicgames": ["https://store.epicgames.com/p/mechabellum-88a843"],
        }
        a, _ = _add(storage, "a", make_post("1", "Astrea и Mechabellum — 100% скидка в Epic Games Store!", "Pikabu",
                                            store_links=links))
        b, _ = _add(storage, "b", make_post(
            "2", "Халява: на PC началась бесплатная раздача двух игр — Mechabellum и Astrea: Six-Sided Oracles",
            "VGTimes"))
        assert a == b == "a"

    def test_headline_only_posts_match_each_other(self, storage):
        a, _ = _add(storage, "a", make_post("1", "Халява: в Steam началась бесплатная раздача Space Menace", "VGTimes"))
        b, _ = _add(storage, "b", make_post("2", "Space Menace — 100% скидка в STEAM!", "Pikabu"))
        assert a == b

    def test_different_games_do_not_match(self, storage):
        a, _ = _add(storage, "a", make_post("1", "Deadshot — 100% скидка в STEAM!", "Pikabu"))
        b, _ = _add(storage, "b", make_post("2", "Space Menace — 100% скидка в STEAM!", "Pikabu"))
        assert a != b

    def test_mobile_and_pc_giveaways_stay_apart(self, storage):
        a, _ = _add(storage, "a", make_post("1", "Mindcop — 100% скидка в Epic Games Store!", "Pikabu"))
        b, _ = _add(storage, "b", make_post("2", "На Android и iOS бесплатно отдают Mindcop", "VGTimes"))
        assert a != b

    def test_late_post_marks_sent_estate_for_edit(self, storage):
        _add(storage, "a", make_post("1", "Deadshot — 100% скидка в STEAM!", "Pikabu"), sent=True)
        target, already_sent = _add(storage, "b", make_post("2", "Халява: раздача Deadshot", "VGTimes"))
        assert target == "a" and already_sent

        assert asyncio.run(storage.get_pending_estates()) == []
        to_edit = asyncio.run(storage.get_estates_to_edit())
        assert [e["estate_id"] for e in to_edit] == ["a"]
        assert to_edit[0]["message_id"] == 777
        assert {p["source"] for p in to_edit[0]["posts"]} == {"Pikabu", "VGTimes"}


# ── NewsMonitor flow ──────────────────────────────────────────────────────

def test_late_duplicate_edits_sent_message_instead_of_posting():
    with patch("src.bot.bot.Bot"), patch("src.bot.bot.request.HTTPXRequest"), patch("main.SQLiteStorage"):
        from main import NewsMonitor
        monitor = NewsMonitor()
    estate = {
        "estate_id": "a" * 32, "title": "Deadshot", "kind": "free:pc", "is_free": True, "description": "",
        "images": [], "tags": [], "games": [], "posts": [{"source": "Pikabu", "post_link": "https://x/1"}],
        "message_id": 777, "message_is_caption": True,
    }
    monitor.bot = MagicMock()
    monitor.bot.formatter = MessageFormatter()
    monitor.bot.send_message = AsyncMock()
    monitor.bot.edit_message = AsyncMock(return_value=True)
    monitor.storage = MagicMock()
    monitor.storage.get_pending_estates = AsyncMock(return_value=[])
    monitor.storage.get_estates_to_edit = AsyncMock(return_value=[estate])
    monitor.storage.clear_estate_edit = AsyncMock()
    monitor.storage.mark_posts_sent = AsyncMock()

    asyncio.run(monitor._flush_pending_estates())

    monitor.bot.send_message.assert_not_called()
    ref, _text = monitor.bot.edit_message.call_args.args
    assert ref == SentMessage(777, is_caption=True)
    monitor.storage.clear_estate_edit.assert_awaited_once()


# ── formatting ────────────────────────────────────────────────────────────

class TestEstateFormatting:
    formatter = MessageFormatter()

    def _estate(self, **kw):
        base = {
            "title": "Deadshot — 100% скидка в STEAM!", "kind": "free:pc", "is_free": True,
            "description": "Раздача продлится до 1 октября.", "images": [], "tags": [],
            "games": [{"name": "Deadshot", "links": {"steam": "https://store.steampowered.com/app/2484180/Deadshot/"},
                       "info": {"steam": {"name": "Deadshot", "price": "Бесплатно", "original_price": "130₴",
                                          "is_free": True,
                                          "short_description": "Fun &amp;quot;ouch!&amp;quot; game &amp; more"}}}],
            "posts": [{"source": "Pikabu", "post_link": "https://pikabu.ru/story/1"},
                      {"source": "VGTimes", "post_link": "https://vgtimes.ru/1"}],
        }
        base.update(kw)
        return base

    def test_single_game_card_has_all_sources_and_no_double_escaping(self):
        text = self.formatter.format_estate_alert(self._estate())
        assert "Бесплатно в Steam" in text
        assert "<s>130₴</s>" in text
        assert "&amp;quot;" not in text and "&amp;amp;" not in text
        assert "Pikabu</a> · <a" in text and "VGTimes</a>" in text
        assert "⏳ до 1 октября" in text
        assert "#steam" in text

    def test_caption_fits_telegram_limit(self):
        long_desc = "Очень длинное описание. " * 200
        reviews = ["Отзыв " * 60] * 2
        estate = self._estate(description=long_desc)
        estate["games"][0]["info"]["steam"].update(short_description=long_desc, top_reviews=reviews,
                                                   genre="Action", metacritic=80)
        text = self.formatter.format_estate_alert(estate)
        assert len(self.formatter.to_plain_text(text)) <= 1024
        assert text.count("<a ") == text.count("</a>")

    def test_giveaway_in_linkless_store_has_no_foreign_price(self):
        estate = self._estate(title="For Honor - 100% скидка в Ubisoft Connect!")
        estate["games"][0]["info"]["steam"].update(is_free=False, price="459₴", original_price=None)
        text = self.formatter.format_estate_alert(estate)
        assert "Бесплатно в Ubisoft Connect" in text
        assert "459₴" not in text
        assert "#ubisoft" in text

    def test_multi_game_list(self):
        estate = self._estate(title="Mechabellum и Astrea — 100% скидка в Epic Games Store!", games=[
            {"name": "Mechabellum", "links": {"epicgames": "https://store.epicgames.com/p/mechabellum-88a843"}, "info": {}},
            {"name": "Astrea", "links": {"epicgames": "https://store.epicgames.com/p/astrea-33c949"}, "info": {}},
        ])
        text = self.formatter.format_estate_alert(estate)
        assert "Бесплатно в Epic Games: 2 игры" in text
        assert "• <b>Mechabellum</b>" in text and "• <b>Astrea</b>" in text

    def test_news_without_links(self):
        text = self.formatter.format_estate_alert(self._estate(games=[], posts=[
            {"source": "VGTimes", "post_link": "https://vgtimes.ru/1"}]))
        assert text.startswith('🎁 <b><a href="https://vgtimes.ru/1">')


def test_steam_bbcode_is_stripped_from_reviews():
    estate = TestEstateFormatting()._estate()
    estate["games"][0]["info"]["steam"]["top_reviews"] = ["[b]Приятное приключение[/b] на один [i]час[/i]"]
    text = MessageFormatter().format_estate_alert(estate)
    assert '💬 "Приятное приключение на один час"' in text


# ── free-forever filter ───────────────────────────────────────────────────

class TestForeverFree:
    giveaway = {"name": "Deadshot", "is_free": True, "discount_pct": 100, "original_price": "130₴", "price": "Бесплатно"}
    f2p = {"name": "TomoTomo", "is_free": True, "discount_pct": 0, "original_price": None, "price": None}

    @pytest.mark.parametrize("title", [
        "В Steam навсегда бесплатными стали сразу 8 игр — от необычного шутера до хоррора",
        "В Steam можно бесплатно забрать в свою библиотеку 5 игр. Есть лавкрафтовский хоррор",
        "В Steam полностью бесплатной стала игра Hayfever про почтальона",
        "Игра о безумных войнах между соседями стала бесплатной — раньше за неё просили 385 рублей в Steam",
    ])
    def test_free_to_play_headlines(self, title):
        assert game_keys.is_permanently_free(title, {})

    @pytest.mark.parametrize("title", [
        "Халява: в Steam началась бесплатная раздача хоррор-шутера Deadshot",
        "В Steam стали временно бесплатными 2 игры. Есть хардкорный онлайн-шутер",
        "Mindcop и Shogun Showdown — 100% скидка в Epic Games Store!",
        "Скидка на Zenonia (Steam)",
    ])
    def test_giveaways_and_deals_pass(self, title):
        assert not game_keys.is_permanently_free(title, {})

    def test_store_data_decides_over_headline(self):
        title = "В Steam можно бесплатно забрать в библиотеку Deadshot"
        assert not game_keys.is_permanently_free(title, {"steam": self.giveaway})
        assert game_keys.is_permanently_free("Халява: TomoTomo", {"steam": self.f2p})

    def test_bundle_with_one_paid_game_is_kept(self):
        assert not game_keys.is_permanently_free("Раздача", {"steam": [self.f2p, self.giveaway]})


def test_flush_skips_estate_that_fresh_steam_data_shows_free_forever():
    from src.services.price_service import GameInfo
    with patch("src.bot.bot.Bot"), patch("src.bot.bot.request.HTTPXRequest"), patch("main.SQLiteStorage"):
        from main import NewsMonitor
        monitor = NewsMonitor()
    estate = {"estate_id": "b" * 32, "title": "Neighbors", "games": [
        {"name": "Neighbors", "links": {"steam": "https://store.steampowered.com/app/1732430/x/"}, "info": {}}]}
    monitor.bot = MagicMock()
    monitor.bot.send_message = AsyncMock()
    monitor._price_service = MagicMock()
    monitor._price_service.get_steam_info = AsyncMock(return_value=GameInfo(name="Neighbors", is_free=True))
    monitor.storage = MagicMock()
    monitor.storage.get_pending_estates = AsyncMock(return_value=[estate])
    monitor.storage.get_estates_to_edit = AsyncMock(return_value=[])
    monitor.storage.mark_estate_flushed = AsyncMock()

    asyncio.run(monitor._flush_pending_estates())

    monitor.bot.send_message.assert_not_called()
    monitor.storage.mark_estate_flushed.assert_awaited_once_with("b" * 32, sent=False)
