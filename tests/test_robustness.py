import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src.models.models import PostMetadata
from src.parsers.stopgame_parser import StopGameParser

_CFG = {
    "stopgame": {
        "target_urls": "https://stopgame.ru/news",
        "selectors": {
            "articles": ".a", "title": ".t a", "link": ".t a", "image": "img", "content": ".c", "date": ".d",
        },
    },
}


class TestRobustness(unittest.TestCase):
    def test_images_dedup_keeps_order(self):
        urls = ["https://x/3.jpg", "https://x/1.jpg", "https://x/3.jpg", "https://x/2.jpg"]
        meta = PostMetadata(images=urls)
        self.assertEqual(meta.images, ["https://x/3.jpg", "https://x/1.jpg", "https://x/2.jpg"])

    def test_stopgame_anchor_without_href(self):
        with patch("src.config.config.settings.PARSERS_CONFIG", _CFG):
            parser = StopGameParser()
        soup = BeautifulSoup('<div class="a"><div class="t"><a>No link</a></div></div>', "html.parser")
        self.assertIsNone(parser._parse_initial_post_data(soup.select_one(".a")))


if __name__ == "__main__":
    unittest.main()


class TestRetryWraps(unittest.TestCase):
    def test_retry_preserves_name(self):
        from src.bot.retry_handler import retry

        @retry(max_retries=1)
        async def my_func():
            """doc"""

        self.assertEqual(my_func.__name__, "my_func")
        self.assertEqual(my_func.__doc__, "doc")
