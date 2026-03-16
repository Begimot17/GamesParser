import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from src.parsers.stopgame_parser import StopGameParser


class TestStopGameParser(unittest.TestCase):
    @patch("src.config.config.settings.PARSERS_CONFIG", {
        "stopgame": {
            "request_timeout": 10,
            "max_text_length": 1000,
            "valid_image_extensions": [".png", ".jpg"],
            "rate_limit_delay": 1,
            "target_urls": "https://stopgame.ru/news",
            "selectors": {
                "articles": ".article-item",
                "title": ".article-title a",
                "link": ".article-title a",
                "image": ".image-wrapper img",
                "content": ".article-content",
                "date": ".article-info .timestamp",
            },
            "stores": {
                "steam": {"domain": "store.steampowered.com"},
                "epicgames": {"domain": "epicgames.com"},
                "gog": {"domain": "gog.com"},
            },
        },
    })
    def setUp(self):
        self.parser = StopGameParser()
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()

    def test_parser_instantiation(self):
        """Tests that the StopGameParser can be instantiated."""
        self.assertIsInstance(self.parser, StopGameParser)

    def test_extract_id(self):
        """Tests the _extract_id method."""
        self.assertEqual(self.parser._extract_id("https://stopgame.ru/newsdata/12345/article-title"), "12345")
        self.assertEqual(self.parser._extract_id("https://stopgame.ru/show/67890/another-article"), "67890")
        self.assertIsNone(self.parser._extract_id("https://stopgame.ru/news/article-title"))
        self.assertIsNone(self.parser._extract_id(""))

    @patch("src.parsers.stopgame_parser.datetime")
    def test_parse_date(self, mock_datetime):
        """Tests the _parse_date method."""
        mock_now = datetime(2024, 7, 20, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        date_str = "15 июля 2024 в 23:22"
        expected_date = datetime(2024, 7, 15, 23, 22, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str), expected_date)

        date_str_today = "сегодня в 10:30"
        expected_date_today = datetime(2024, 7, 20, 10, 30, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_today), expected_date_today)

        date_str_yesterday = "вчера в 18:00"
        expected_date_yesterday = datetime(2024, 7, 19, 18, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_yesterday), expected_date_yesterday)

        self.assertIsNone(self.parser._parse_date("invalid date string"))
        self.assertIsNone(self.parser._parse_date(""))

    def test_extract_store_links(self):
        """Tests the _extract_store_links method."""
        html_content = """
        <div class="article-content">
            <p>Buy it on <a href="https://store.steampowered.com/app/12345/">Steam</a>!</p>
            <p>Get it from <a href="https://www.epicgames.com/p/cool-game">Epic Games Store</a>.</p>
            <p>Also available on <a href="https://www.gog.com/game/awesome_title">GOG</a>.</p>
            <p>A regular link: <a href="https://www.stopgame.ru/news">StopGame News</a></p>
            <p>Invalid Steam link: <a href="https://store.steampowered.com/about/">About Steam</a></p>
        </div>
        """
        article_html = BeautifulSoup(html_content, "html.parser").find("div", class_="article-content")

        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/",
            "epicgames": "https://www.epicgames.com/p/cool-game",
            "gog": "https://www.gog.com/game/awesome_title",
        }
        self.assertDictEqual(self.parser._extract_store_links(article_html), expected_links)

        no_links_html = """<div class="article-content">No store links here</div>"""
        no_links_article = BeautifulSoup(no_links_html, "html.parser").find("div", class_="article-content")
        self.assertDictEqual(self.parser._extract_store_links(no_links_article), {})

        empty_article = BeautifulSoup("", "html.parser")
        self.assertDictEqual(self.parser._extract_store_links(empty_article), {})

    @patch("src.config.config.settings.PARSERS_CONFIG", {
        "stopgame": {
            "request_timeout": 10,
            "max_text_length": 1000,
            "valid_image_extensions": [".png", ".jpg"],
            "rate_limit_delay": 1,
            "target_urls": "https://stopgame.ru/news",
            "selectors": {
                "articles": ".article-item",
                "title": ".article-title a",
                "link": ".article-title a",
                "image": ".image-wrapper img",
                "content": ".article-content",
                "date": ".article-info .timestamp",
            },
            "stores": {},
        },
    })
    def test_parse_article_fetches_content(self):
        """_parse_article должен загружать контент из полной страницы."""
        import asyncio

        article_html = BeautifulSoup("""
        <div class="article-item">
            <div class="article-title">
                <a href="https://stopgame.ru/newsdata/12345/title">Test Article</a>
            </div>
            <div class="image-wrapper"><img src="https://cdn.example.com/img.jpg"></div>
            <div class="article-info"><span class="timestamp">15 июля 2024 в 12:00</span></div>
        </div>
        """, "html.parser").find("div", class_="article-item")

        self.parser._fetch_article_data = AsyncMock(return_value=("Full article content here", []))

        post = asyncio.run(self.parser._parse_article(article_html))

        self.assertIsNotNone(post)
        self.assertEqual(post.content, "Full article content here")
        self.parser._fetch_article_data.assert_called_once()


class TestStopGamePagination(unittest.TestCase):
    @patch("src.config.config.settings.PARSERS_CONFIG", {
        "stopgame": {
            "request_timeout": 10,
            "max_text_length": 1000,
            "valid_image_extensions": [".png", ".jpg"],
            "rate_limit_delay": 1,
            "initial_pages": 3,
            "target_urls": "https://stopgame.ru/news",
            "selectors": {"articles": ".a", "title": ".t", "link": ".l", "content": ".c", "date": ".d"},
            "stores": {},
        },
    })
    def setUp(self):
        self.parser = StopGameParser()

    def test_build_page_urls_single(self):
        urls = self.parser._build_page_urls(1)
        self.assertEqual(urls, ["https://stopgame.ru/news"])

    def test_build_page_urls_multi(self):
        urls = self.parser._build_page_urls(3)
        self.assertEqual(urls, [
            "https://stopgame.ru/news",
            "https://stopgame.ru/news/p2",
            "https://stopgame.ru/news/p3",
        ])

    def test_is_first_run_defaults_false(self):
        self.assertFalse(self.parser._is_first_run)


if __name__ == "__main__":
    unittest.main()
