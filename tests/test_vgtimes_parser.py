import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bs4 import BeautifulSoup

from src.parsers.vgtimes_parser import VGTimesParser


VGTIMES_CONFIG = {
    "vgtimes": {
        "request_timeout": 10,
        "max_text_length": 1000,
        "valid_image_extensions": [".png", ".jpg"],
        "rate_limit_delay": 1,
        "target_urls": "https://vgtimes.ru/free/",
        "selectors": {
            "articles": "ul.list-items > li",
            "title": "div.item-name.type0 a:first-child",
            "link": "div.item-name.type0 a:first-child",
            "image": "div.image_wrap.type0 img",
            "rating": "div.rrating div.text",
            "store_links": 'a.l_ks[target="_blank"]',
            "content": "div.article_text",
            "date": "div.date",
        },
        "stores": {
            "steam": {"domain": "store.steampowered.com", "validation_regex": "/app/\\d+/"},
            "epicgames": {"domain": "epicgames.com", "validation_regex": "/p/[^/?#]+"},
            "gog": {"domain": "gog.com", "validation_regex": "/game/[^/?#]+"},
        },
    },
}


class TestVGTimesParser(unittest.IsolatedAsyncioTestCase):
    @patch("src.config.config.settings.PARSERS_CONFIG", VGTIMES_CONFIG)
    async def asyncSetUp(self):
        self.parser = VGTimesParser()
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()

    async def test_parser_instantiation(self):
        """Tests that the VGTimesParser can be instantiated."""
        self.assertIsInstance(self.parser, VGTimesParser)

    async def test_extract_id(self):
        """Tests the _extract_id method."""
        self.assertEqual(self.parser._extract_id("https://vgtimes.ru/games/12345-game-name/"), "12345")
        self.assertIsNone(self.parser._extract_id("https://vgtimes.ru/games/game-name/"))
        self.assertIsNone(self.parser._extract_id(""))

    async def test_parse_date(self):
        """Tests the _parse_date method."""
        date_str = "5 апреля 2025, 23:22"
        expected_date = datetime(2025, 4, 5, 23, 22, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str), expected_date)

        date_str_feb = "10 февраля 2024, 10:00"
        expected_date_feb = datetime(2024, 2, 10, 10, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_feb), expected_date_feb)

        self.assertIsNone(self.parser._parse_date("invalid date string"))
        self.assertIsNone(self.parser._parse_date(""))

    async def test_extract_store_links(self):
        """Tests the _extract_store_links method."""
        html_content = """
        <div class="item">
            <a class="l_ks" target="_blank" href="https://store.steampowered.com/app/12345/">Steam Link</a>
            <a class="l_ks" target="_blank" href="https://www.epicgames.com/p/game-name">Epic Games Link</a>
            <a class="l_ks" target="_blank" href="https://www.gog.com/game/another_game">GOG Link</a>
            <a class="l_ks" target="_blank" href="https://www.unsupported.com/game">Unsupported Link</a>
        </div>
        """
        article_html = BeautifulSoup(html_content, "html.parser").find("div", class_="item")

        # _clean_store_url is now sync
        self.parser._clean_store_url = MagicMock(side_effect=lambda url, name: url)

        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/",
            "epicgames": "https://www.epicgames.com/p/game-name",
            "gog": "https://www.gog.com/game/another_game",
        }
        self.assertDictEqual(self.parser._extract_store_links(article_html), expected_links)

        no_links_html = """<div class="item">No links here</div>"""
        no_links_article = BeautifulSoup(no_links_html, "html.parser").find("div", class_="item")
        self.assertDictEqual(self.parser._extract_store_links(no_links_article), {})

        empty_article = BeautifulSoup("", "html.parser")
        self.assertDictEqual(self.parser._extract_store_links(empty_article), {})

    async def test_extract_store_links_filters_generic_urls(self):
        """Generic/landing store URLs (no app/slug ID) must be rejected by validation_regex."""
        html_content = """
        <div class="item">
            <a class="l_ks" target="_blank" href="https://store.steampowered.com/about/">Steam landing</a>
            <a class="l_ks" target="_blank" href="https://www.gog.com/en/games">GOG category</a>
            <a class="l_ks" target="_blank" href="https://store.epicgames.com/ru/free-games">EGS landing</a>
        </div>
        """
        article_html = BeautifulSoup(html_content, "html.parser").find("div", class_="item")
        result = self.parser._extract_store_links(article_html)
        self.assertDictEqual(result, {}, "Generic URLs should be filtered out by validation_regex")

    async def test_extract_store_links_accepts_specific_urls(self):
        """Specific game store URLs (with app/slug ID) must pass validation_regex."""
        html_content = """
        <div class="item">
            <a class="l_ks" target="_blank" href="https://store.steampowered.com/app/730/CounterStrike2/">Steam app</a>
            <a class="l_ks" target="_blank" href="https://www.gog.com/game/witcher_3">GOG game</a>
            <a class="l_ks" target="_blank" href="https://store.epicgames.com/p/fortnite">EGS game</a>
        </div>
        """
        article_html = BeautifulSoup(html_content, "html.parser").find("div", class_="item")
        result = self.parser._extract_store_links(article_html)
        self.assertIn("steam", result)
        self.assertIn("gog", result)
        self.assertIn("epicgames", result)

    async def test_clean_store_url_decodes_go_url(self):
        """URL в формате /go/?encoded_url должен декодироваться без HTTP-запроса."""
        from urllib.parse import quote

        store_url = "https://store.steampowered.com/app/123/"
        go_url = f"https://vgtimes.ru/go/?{quote(store_url, safe='')}"

        result = self.parser._clean_store_url(go_url, "steam")

        assert result == store_url

    async def test_clean_store_url_epicgames_decoded(self):
        """EGS URL декодируется из /go/? формата."""
        from urllib.parse import quote

        store_url = "https://store.epicgames.com/ru/p/some-game"
        go_url = f"https://vgtimes.ru/go/?{quote(store_url, safe='')}"

        result = self.parser._clean_store_url(go_url, "epicgames")

        assert result == store_url


class TestVGTimesPagination(unittest.IsolatedAsyncioTestCase):
    @patch("src.config.config.settings.PARSERS_CONFIG", {
        "vgtimes": {
            "request_timeout": 10,
            "max_text_length": 1000,
            "valid_image_extensions": [".png", ".jpg"],
            "rate_limit_delay": 1,
            "initial_pages": 3,
            "target_urls": "https://vgtimes.ru/free/",
            "selectors": {"articles": ".a", "title": ".t", "link": ".l", "content": ".c", "date": ".d", "image": ".i", "rating": ".r", "store_links": ".s"},
            "stores": {},
        },
    })
    async def asyncSetUp(self):
        self.parser = VGTimesParser()

    async def test_build_page_urls_single(self):
        urls = self.parser._build_page_urls(1)
        self.assertEqual(urls, ["https://vgtimes.ru/free/"])

    async def test_build_page_urls_multi(self):
        urls = self.parser._build_page_urls(3)
        self.assertEqual(urls, [
            "https://vgtimes.ru/free/",
            "https://vgtimes.ru/free/?PAGEN_1=2",
            "https://vgtimes.ru/free/?PAGEN_1=3",
        ])

    async def test_is_first_run_defaults_false(self):
        self.assertFalse(self.parser._is_first_run)


if __name__ == "__main__":
    unittest.main()
