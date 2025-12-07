import unittest
from unittest.mock import patch, AsyncMock
from src.parsers.pikabu_parser import PikabuParser
from bs4 import BeautifulSoup

class TestPikabuParser(unittest.TestCase):
    @patch('src.config.config.Config.PARSERS_CONFIG', {
        'pikabu': {
            'request_timeout': 10,
            'max_text_length': 1000,
            'valid_image_extensions': ['.png', '.jpg'],
            'rate_limit_delay': 1,
            'target_urls': 'http://test.com',
            'selectors': {'test_selector': '.test'},
            'stores': {
                'steam': {
                    'domain': 'store.steampowered.com',
                    'validation_regex': '/app/\\d+/'
                },
                'epicgames': {
                    'domain': 'epicgames.com',
                    'validation_regex': '/p/[^/]+$'
                },
                'itch': {
                    'domain': 'itch.io'
                },
                'gog': {
                    'domain': 'gog.com',
                    'validation_regex': '/game/[^/]+$'
                }
            }
        }
    })
    def setUp(self):
        self.parser = PikabuParser()
        # Mock the async methods that are not under test in these specific unit tests
        self.parser._fetch_page = AsyncMock(return_value="<html><body></body></html>")
        self.parser._fetch_full_page_text = AsyncMock(return_value="")
        self.parser.llm = AsyncMock()
        self.parser.storage = AsyncMock()
        self.parser.storage.is_processed.return_value = False

    def test_parser_instantiation(self):
        """Tests that the PikabuParser can be instantiated."""
        self.assertIsInstance(self.parser, PikabuParser)

    def test_parser_configuration(self):
        """Tests that the PikabuParser correctly loads its configuration."""
        self.assertEqual(self.parser.REQUEST_TIMEOUT, 10)
        self.assertEqual(self.parser.MAX_TEXT_LENGTH, 1000)
        self.assertEqual(self.parser.VALID_IMAGE_EXTENSIONS, ('.png', '.jpg'))
        self.assertEqual(self.parser.RATE_LIMIT_DELAY, 1)
        self.assertEqual(self.parser.TARGET_URLS, ['http://test.com'])
        self.assertEqual(self.parser.SELECTORS, {'test_selector': '.test'})
        self.assertIn('steam', self.parser.STORE_CONFIG)
        self.assertIn('epicgames', self.parser.STORE_CONFIG)

    def test_normalize_url(self):
        """Tests the _normalize_url method."""
        self.assertEqual(self.parser._normalize_url("//example.com/path"), "https://example.com/path")
        self.assertEqual(self.parser._normalize_url("/path", base_url="https://base.com"), "https://base.com/path")
        self.assertEqual(self.parser._normalize_url("example.com/path"), "https://example.com/path")
        self.assertEqual(self.parser._normalize_url("https://example.com/path"), "https://example.com/path")
        self.assertEqual(self.parser._normalize_url(""), "")

    def test_clean_text(self):
        """Tests the _clean_text method."""
        # Temporarily set MAX_TEXT_LENGTH for this test
        self.parser.MAX_TEXT_LENGTH = 30
        short_text = "This is a short text."
        long_text = "This is a very long text that should be truncated."
        self.assertEqual(self.parser._clean_text(short_text), short_text)
        self.assertEqual(self.parser._clean_text(long_text), "This is a very long text that ...")

    def test_clean_store_url(self):
        """Tests the _clean_store_url method for various stores."""
        # Valid Steam URL
        self.assertEqual(self.parser._clean_store_url("https://store.steampowered.com/app/12345/", "steam"), "https://store.steampowered.com/app/12345/")
        # Invalid Steam URL (missing app ID)
        self.assertEqual(self.parser._clean_store_url("https://store.steampowered.com/about/", "steam"), "")
        # Valid Epic Games URL
        self.assertEqual(self.parser._clean_store_url("https://www.epicgames.com/p/game-name", "epicgames"), "https://www.epicgames.com/p/game-name")
        # Invalid Epic Games URL (missing product slug)
        self.assertEqual(self.parser._clean_store_url("https://www.epicgames.com/store/", "epicgames"), "")
        # Valid Itch.io URL
        self.assertEqual(self.parser._clean_store_url("https://user.itch.io/game-name", "itch"), "https://user.itch.io/game-name")
        # Invalid Itch.io URL (too short path)
        self.assertEqual(self.parser._clean_store_url("https://itch.io", "itch"), "")
        self.assertEqual(self.parser._clean_store_url("https://user.itch.io", "itch"), "")
        # Valid GOG URL
        self.assertEqual(self.parser._clean_store_url("https://www.gog.com/game/game_name", "gog"), "https://www.gog.com/game/game_name")
        # Invalid GOG URL (missing game slug)
        self.assertEqual(self.parser._clean_store_url("https://www.gog.com/en/games", "gog"), "")
        # URL for an unsupported store
        self.assertEqual(self.parser._clean_store_url("https://www.origin.com/game", "origin"), "")
        # Empty URL
        self.assertEqual(self.parser._clean_store_url("", "steam"), "")
        # URL with query parameters/fragments
        self.assertEqual(self.parser._clean_store_url("https://store.steampowered.com/app/12345/?param=value#fragment", "steam"), "https://store.steampowered.com/app/12345/")

    def test_extract_store_links(self):
        """Tests the _extract_store_links method."""
        text_with_links = """
        Check out this game on Steam: https://store.steampowered.com/app/12345/Game_Title/
        Or on Epic Games: https://www.epicgames.com/p/another-game
        And also on GOG: https://www.gog.com/game/cool_game
        An invalid Steam link: https://store.steampowered.com/news/
        An itch.io link: https://dev.itch.io/my-game
        Some other link: https://www.google.com
        """
        expected_links = {
            "steam": "https://store.steampowered.com/app/12345/Game_Title/",
            "epicgames": "https://www.epicgames.com/p/another-game",
            "gog": "https://www.gog.com/game/cool_game",
            "itch": "https://dev.itch.io/my-game"
        }
        extracted_links = self.parser._extract_store_links(text_with_links)
        self.assertDictEqual(extracted_links, expected_links)

        text_without_links = "No store links here."
        self.assertDictEqual(self.parser._extract_store_links(text_without_links), {})

        text_with_invalid_links = """
        Invalid Steam: https://store.steampowered.com/about/
        Invalid Epic: https://www.epicgames.com/store/
        Invalid Itch: https://itch.io
        """
        self.assertDictEqual(self.parser._extract_store_links(text_with_invalid_links), {})

if __name__ == '__main__':
    unittest.main()
