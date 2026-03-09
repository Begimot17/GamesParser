import unittest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup, Tag
from src.parsers.vgtimes_parser import VGTimesParser

class TestVGTimesParser(unittest.IsolatedAsyncioTestCase):
    @patch('src.config.config.settings.PARSERS_CONFIG', {
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
    async def asyncSetUp(self):
        self.parser = VGTimesParser()
        # Mock async methods not directly under test
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()
        self.parser.storage = AsyncMock()
        self.parser.storage.is_processed.return_value = False

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
        article_html = BeautifulSoup(html_content, 'html.parser').find('div', class_='item')
        
        # Ensure _clean_store_url is mocked or works
        # Since _extract_store_links calls _clean_store_url which calls self.session.head
        # we might need to mock _clean_store_url or self.session.
        # But VGTimesParser._clean_store_url handles session HEAD requests.
        # It's better to mock _clean_store_url to avoid network calls.
        
        self.parser._clean_store_url = AsyncMock(side_effect=lambda url, name: url)

        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/",
            "epicgames": "https://www.epicgames.com/p/game-name",
            "gog": "https://www.gog.com/game/another_game"
        }
        self.assertDictEqual(await self.parser._extract_store_links(article_html), expected_links)

        # Test with no store links
        no_links_html = """<div class="item">No links here</div>"""
        no_links_article = BeautifulSoup(no_links_html, 'html.parser').find('div', class_='item')
        self.assertDictEqual(await self.parser._extract_store_links(no_links_article), {})

        # Test with empty article_html
        empty_article = BeautifulSoup("", 'html.parser')
        self.assertDictEqual(await self.parser._extract_store_links(empty_article), {})

    @patch('src.config.config.settings.PARSERS_CONFIG', {
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
    async def test_clean_store_url_uses_client_timeout(self):
        """HEAD-запрос для redirect должен использовать aiohttp.ClientTimeout."""
        import aiohttp

        captured_kwargs = {}

        mock_response = unittest.mock.AsyncMock()
        mock_response.url = "https://store.steampowered.com/app/123/"
        mock_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = unittest.mock.AsyncMock(return_value=False)

        def fake_head(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_session = unittest.mock.MagicMock()
        mock_session.closed = False
        mock_session.head = fake_head
        self.parser.session = mock_session

        await self.parser._clean_store_url("https://vgtimes.ru/go/12345", "steam")

        assert "timeout" in captured_kwargs
        assert isinstance(captured_kwargs["timeout"], aiohttp.ClientTimeout)


if __name__ == '__main__':
    unittest.main()
