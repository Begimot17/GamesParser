import unittest
import asyncio
from unittest.mock import patch, AsyncMock
from src.parsers.parser_manager import ParserManager
from src.models.models import Post, PostMetadata

# Sample HTML content for mocking
PIKABU_SAMPLE_HTML = """
<article data-story-id="12345">
    <h2 class="story__title"><a class="story__title-link" href="https://pikabu.ru/story/test_post_pikabu">Test Post Pikabu</a></h2>
    <div class="story__content">Content of Pikabu post.</div>
    <div class="story__rating-count">100</div>
    <time class="story__datetime" datetime="2024-07-20T10:00:00Z"></time>
    <div class="story-block_type_image"><img class="story-image__image" src="https://pikabu.ru/img/pikabu_image.jpg"></div>
</article>
"""

VGT_SAMPLE_HTML = """
<ul class="list-items">
    <li>
        <div class="item-name type0"><a href="https://vgtimes.ru/games/67890-test-post-vgtimes/">Test Post VGTimes</a></div>
        <div class="image_wrap type0"><img data-src="https://vgtimes.ru/img/vgtimes_image.jpg"></div>
        <div class="rrating"><div class="text">50</div></div>
        <div class="date">20 июля 2024, 11:00</div>
        <a class="l_ks" target="_blank" href="https://store.steampowered.com/app/54321/">Steam Link VGT</a>
    </li>
</ul>
"""

STOPGAME_SAMPLE_HTML = """
<div class="article-item">
    <div class="article-title"><a href="https://stopgame.ru/newsdata/98765/test-post-stopgame">Test Post StopGame</a></div>
    <div class="image-wrapper"><img src="https://stopgame.ru/img/stopgame_image.jpg"></div>
    <div class="article-info"><span class="timestamp">20 июля 2024, 12:00</span></div>
    <div class="article-content">Content of StopGame post. <a href="https://www.epicgames.com/p/stopgame-game">Epic Link SG</a></div>
</div>
"""

class TestParserManager(unittest.IsolatedAsyncioTestCase):
    @patch('src.config.config.Config.PARSERS_CONFIG', {
        'pikabu': {
            'request_timeout': 10, 'max_text_length': 1000, 'valid_image_extensions': ['.jpg'],
            'rate_limit_delay': 1, 'target_urls': 'http://pikabu.test',
            'selectors': {
                "articles": "article[data-story-id]", "title": "h2.story__title a.story__title-link",
                "link": "a.story__title-link", "content": "div.story__content", "rating": "div.story__rating-count",
                "images": ["div.story-block_type_image img.story-image__image"], "date": "time.story__datetime",
            },
            'stores': {'steam': {'domain': 'store.steampowered.com', 'validation_regex': '/app/\\d+/'}}
        },
        'vgtimes': {
            'request_timeout': 10, 'max_text_length': 1000, 'valid_image_extensions': ['.jpg'],
            'rate_limit_delay': 1, 'target_urls': 'http://vgtimes.test',
            'selectors': {
                "articles": "ul.list-items > li", "title": "div.item-name.type0 a:first-child",
                "link": "div.item-name.type0 a:first-child", "image": "div.image_wrap.type0 img",
                "rating": "div.rrating div.text", "store_links": 'a.l_ks[target="_blank"]', "date": "div.date",
            },
            'stores': {'steam': {'domain': 'store.steampowered.com'}}
        },
        'stopgame': {
            'request_timeout': 10, 'max_text_length': 1000, 'valid_image_extensions': ['.jpg'],
            'rate_limit_delay': 1, 'target_urls': 'http://stopgame.test',
            'selectors': {
                "articles": ".article-item", "title": ".article-title a", "link": ".article-title a",
                "image": ".image-wrapper img", "content": ".article-content", "date": ".article-info .timestamp",
            },
            'stores': {'epicgames': {'domain': 'epicgames.com'}}
        }
    })
    @patch('src.parsers.pikabu_parser.LLMG4F', AsyncMock)
    @patch('src.parsers.vgtimes_parser.LLMG4F', AsyncMock)
    @patch('src.parsers.stopgame_parser.LLMG4F', AsyncMock)
    @patch('src.parsers.pikabu_parser.JsonStorage', AsyncMock)
    @patch('src.parsers.vgtimes_parser.JsonStorage', AsyncMock)
    @patch('src.parsers.stopgame_parser.JsonStorage', AsyncMock)
    async def asyncSetUp(self):
        self.manager = ParserManager()
        
        # Mock _fetch_page for each parser instance
        for parser in self.manager.parsers:
            parser._fetch_page = AsyncMock(side_effect=self._mock_fetch_page)
            parser._fetch_full_page_text = AsyncMock(side_effect=self._mock_fetch_full_page_text)
            parser.storage.is_processed.return_value = False # Ensure posts are processed

    async def _mock_fetch_page(self, url: str) -> str:
        if "pikabu.test" in url:
            return PIKABU_SAMPLE_HTML
        elif "vgtimes.test" in url:
            return VGT_SAMPLE_HTML
        elif "stopgame.test" in url:
            return STOPGAME_SAMPLE_HTML
        return ""

    async def _mock_fetch_full_page_text(self, url: str) -> str:
        # For simplicity, return the same content as _fetch_page for full text
        # In a real scenario, this might fetch a different, more detailed page
        return await self._mock_fetch_page(url)

    async def test_fetch_all_posts(self):
        """Tests that ParserManager can fetch posts from all configured parsers."""
        posts = await self.manager.fetch_all_posts()
        self.assertEqual(len(posts), 3) # One post from each parser

        # Verify content of Pikabu post
        pikabu_post = next(p for p in posts if p.id == "12345")
        self.assertIsNotNone(pikabu_post)
        self.assertEqual(pikabu_post.title, "Test Post Pikabu")
        self.assertEqual(pikabu_post.link, "https://pikabu.ru/story/test_post_pikabu")
        self.assertIn("Content of Pikabu post.", pikabu_post.content)
        self.assertEqual(pikabu_post.metadata.rating, "100")
        self.assertEqual(pikabu_post.metadata.images, ["https://pikabu.ru/img/pikabu_image.jpg"])

        # Verify content of VGTimes post
        vgtimes_post = next(p for p in posts if p.id == "67890")
        self.assertIsNotNone(vgtimes_post)
        self.assertEqual(vgtimes_post.title, "Test Post VGTimes")
        self.assertEqual(vgtimes_post.link, "https://vgtimes.ru/games/67890-test-post-vgtimes/")
        self.assertEqual(vgtimes_post.metadata.rating, "50")
        self.assertEqual(vgtimes_post.metadata.images, ["https://vgtimes.ru/img/vgtimes_image.jpg"])
        self.assertIn("steam", vgtimes_post.metadata.store_links)

        # Verify content of StopGame post
        stopgame_post = next(p for p in posts if p.id == "98765")
        self.assertIsNotNone(stopgame_post)
        self.assertEqual(stopgame_post.title, "Test Post StopGame")
        self.assertEqual(stopgame_post.link, "https://stopgame.ru/newsdata/98765/test-post-stopgame")
        self.assertIn("Content of StopGame post.", stopgame_post.content)
        self.assertEqual(stopgame_post.metadata.images, ["https://stopgame.ru/img/stopgame_image.jpg"])
        self.assertIn("epicgames", stopgame_post.metadata.store_links)

    async def test_stream_posts(self):
        """Tests that ParserManager can stream posts from all configured parsers."""
        streamed_posts = []
        async for post in self.manager.stream_posts():
            streamed_posts.append(post)
        
        self.assertEqual(len(streamed_posts), 3) # One post from each parser
        post_ids = {p.id for p in streamed_posts}
        self.assertIn("12345", post_ids)
        self.assertIn("67890", post_ids)
        self.assertIn("98765", post_ids)

if __name__ == '__main__':
    unittest.main()
