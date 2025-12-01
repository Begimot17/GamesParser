import unittest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup, Tag
from src.parsers.vgtimes_parser import VGTimesParser

class TestVGTimesParser(unittest.TestCase):
    @patch('src.config.config.Config.PARSERS_CONFIG', {
        'vgtimes': {
            'request_timeout': 10,
            'max_text_length': 1000,
            'valid_image_extensions': ['.png', '.jpg'],
            'rate_limit_delay': 1,
            'target_urls': 'https://vgtimes.ru/free/',
            'selectors': {
                "articles": "ul.list-items > li",
                "title": "div.item-name.type0 a:first-child",
                "link": "div.item-name.type0 a:first-child",
                "image": "div.image_wrap.type0 img",
                "rating": "div.rrating div.text",
                "store_links": 'a.l_ks[target="_blank"]',
                "content": "div.article_text",
                "date": "div.date",
            },
            'stores': {
                'steam': {'domain': 'store.steampowered.com'},
                'epicgames': {'domain': 'epicgames.com'},
                'gog': {'domain': 'gog.com'}
            }
        }
    })
    def setUp(self):
        self.parser = VGTimesParser()
        # Mock async methods not directly under test
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()
        self.parser.storage = AsyncMock()
        self.parser.storage.is_processed.return_value = False

    def test_parser_instantiation(self):
        """Tests that the VGTimesParser can be instantiated."""
        self.assertIsInstance(self.parser, VGTimesParser)

    def test_extract_id(self):
        """Tests the _extract_id method."""
        self.assertEqual(self.parser._extract_id("https://vgtimes.ru/games/12345-game-name/"), "12345")
        self.assertIsNone(self.parser._extract_id("https://vgtimes.ru/games/game-name/"))
        self.assertIsNone(self.parser._extract_id(""))

    def test_parse_date(self):
        """Tests the _parse_date method."""
        # Test with a known date format
        date_str = "5 апреля 2025, 23:22"
        expected_date = datetime(2025, 4, 5, 23, 22, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str), expected_date)

        # Test with a different month
        date_str_feb = "10 февраля 2024, 10:00"
        expected_date_feb = datetime(2024, 2, 10, 10, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(self.parser._parse_date(date_str_feb), expected_date_feb)

        # Test with invalid format
        self.assertIsNone(self.parser._parse_date("invalid date string"))
        self.assertIsNone(self.parser._parse_date(""))

    def test_extract_store_links(self):
        """Tests the _extract_store_links method."""
        html_content = """
        <div class="item">
            <a class="l_ks" target="_blank" href="https://store.steampowered.com/app/12345/">Steam Link</a>
            <a class="l_ks" target="_blank" href="https://www.epicgames.com/p/game-name">Epic Games Link</a>
            <a class="l_ks" target="_blank" href="https://www.gog.com/game/another_game">GOG Link</a>
            <a class="l_ks" target="_blank" href="https://www.unsupported.com/game">Unsupported Link</a>
        </div>
        """
        article_html = BeautifulSoup(html_content, 'html.parser').find('div', class_='item')
        
        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/",
            "epicgames": "https://www.epicgames.com/p/game-name",
            "gog": "https://www.gog.com/game/another_game"
        }
        self.assertDictEqual(self.parser._extract_store_links(article_html), expected_links)

        # Test with no store links
        no_links_html = """<div class="item">No links here</div>"""
        no_links_article = BeautifulSoup(no_links_html, 'html.parser').find('div', class_='item')
        self.assertDictEqual(self.parser._extract_store_links(no_links_article), {})

        # Test with empty article_html
        empty_article = BeautifulSoup("", 'html.parser')
        self.assertDictEqual(self.parser._extract_store_links(empty_article), {})

if __name__ == '__main__':
    unittest.main()
