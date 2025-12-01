import unittest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup, Tag
from src.parsers.stopgame_parser import StopGameParser

class TestStopGameParser(unittest.TestCase):
    @patch('src.config.config.Config.PARSERS_CONFIG', {
        'stopgame': {
            'request_timeout': 10,
            'max_text_length': 1000,
            'valid_image_extensions': ['.png', '.jpg'],
            'rate_limit_delay': 1,
            'target_urls': 'https://stopgame.ru/news',
            'selectors': {
                "articles": ".article-item",
                "title": ".article-title a",
                "link": ".article-title a",
                "image": ".image-wrapper img",
                "content": ".article-content",
                "date": ".article-info .timestamp",
            },
            'stores': {
                'steam': {'domain': 'store.steampowered.com'},
                'epicgames': {'domain': 'epicgames.com'},
                'gog': {'domain': 'gog.com'}
            }
        }
    })
    def setUp(self):
        self.parser = StopGameParser()
        # Mock async methods not directly under test
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()
        self.parser.storage = AsyncMock()
        self.parser.storage.is_processed.return_value = False

    def test_parser_instantiation(self):
        """Tests that the StopGameParser can be instantiated."""
        self.assertIsInstance(self.parser, StopGameParser)

    def test_extract_id(self):
        """Tests the _extract_id method."""
        self.assertEqual(self.parser._extract_id("https://stopgame.ru/newsdata/12345/article-title"), "12345")
        self.assertEqual(self.parser._extract_id("https://stopgame.ru/show/67890/another-article"), "67890")
        self.assertIsNone(self.parser._extract_id("https://stopgame.ru/news/article-title"))
        self.assertIsNone(self.parser._extract_id(""))

    @patch('src.parsers.stopgame_parser.datetime')
    def test_parse_date(self, mock_datetime):
        """Tests the _parse_date method."""
        # Mock datetime.now() for consistent testing of relative dates
        mock_now = datetime(2024, 7, 20, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime # Keep original strptime

        # Test with a known date format
        date_str = "15 июля 2024, 23:22"
        expected_date = datetime(2024, 7, 15, 23, 22, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str), expected_date)

        # Test "сегодня"
        date_str_today = "сегодня в 10:30"
        expected_date_today = datetime(2024, 7, 20, 10, 30, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_today), expected_date_today)

        # Test "вчера"
        date_str_yesterday = "вчера в 18:00"
        expected_date_yesterday = datetime(2024, 7, 19, 18, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_yesterday), expected_date_yesterday)

        # Test with invalid format
        self.assertIsNone(self.parser._parse_date("invalid date string"))
        self.assertIsNone(self.parser._parse_date(""))

    def test_extract_store_links(self):
        """Tests the _extract_store_links method."""
        html_content = """
        <div class="article-content">
            <p>Buy it on <a href="https://store.steampowered.com/app/12345/">Steam</a>!</p>
            <p>Get it from <a href="https://www.epicgames.com/p/cool-game">Epic Games Store</a>.</p>
            <p>Also available on <a href="https://www.gog.com/game/awesome_title">GOG</a>.</p>
            <p>A regular link: <a href="https://www.stopgame.ru/news">StopGame News</a></            
            <p>Invalid Steam link: <a href="https://store.steampowered.com/about/">About Steam</a></p>
        </div>
        """
        article_html = BeautifulSoup(html_content, 'html.parser').find('div', class_='article-content')
        
        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/",
            "epicgames": "https://www.epicgames.com/p/cool-game",
            "gog": "https://www.gog.com/game/awesome_title"
        }
        self.assertDictEqual(self.parser._extract_store_links(article_html), expected_links)

        # Test with no store links
        no_links_html = """<div class="article-content">No store links here</div>"""
        no_links_article = BeautifulSoup(no_links_html, 'html.parser').find('div', class_='article-content')
        self.assertDictEqual(self.parser._extract_store_links(no_links_article), {})

        # Test with empty article_html
        empty_article = BeautifulSoup("", 'html.parser')
        self.assertDictEqual(self.parser._extract_store_links(empty_article), {})

if __name__ == '__main__':
    unittest.main()
