import unittest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from src.parsers.parser_manager import ParserManager


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
    async def asyncSetUp(self):
        # Create mock parsers - using MagicMock for broader compatibility with async iteration mocking
        self.mock_pikabu = MagicMock()
        self.mock_pikabu.__class__.__name__ = 'PikabuParser'
        
        self.mock_vgtimes = MagicMock()
        self.mock_vgtimes.__class__.__name__ = 'VGTimesParser'
        
        self.mock_stopgame = MagicMock()
        self.mock_stopgame.__class__.__name__ = 'StopGameParser'

        # Setup context managers for parsers (async with parser:)
        # Since they are MagicMocks, we need to mock __aenter__ and __aexit__ to return AsyncMocks or handle async nature
        self.mock_pikabu.__aenter__ = AsyncMock(return_value=self.mock_pikabu)
        self.mock_pikabu.__aexit__ = AsyncMock(return_value=None)
        
        self.mock_vgtimes.__aenter__ = AsyncMock(return_value=self.mock_vgtimes)
        self.mock_vgtimes.__aexit__ = AsyncMock(return_value=None)
        
        self.mock_stopgame.__aenter__ = AsyncMock(return_value=self.mock_stopgame)
        self.mock_stopgame.__aexit__ = AsyncMock(return_value=None)

        # Also mock fetch_posts to be awaitable
        self.mock_pikabu.fetch_posts = AsyncMock()
        self.mock_vgtimes.fetch_posts = AsyncMock()
        self.mock_stopgame.fetch_posts = AsyncMock()

        self.parsers = [self.mock_vgtimes, self.mock_pikabu, self.mock_stopgame]
        self.manager = ParserManager(parsers=self.parsers)

    async def test_fetch_all_posts(self):
        """Tests that ParserManager can fetch posts from all configured parsers."""
        # Setup mock returns
        post_pikabu = MagicMock()
        post_pikabu.id = "12345"
        post_pikabu.title = "Test Post Pikabu"
        
        post_vgtimes = MagicMock()
        post_vgtimes.id = "67890"
        post_vgtimes.title = "Test Post VGTimes"
        
        post_stopgame = MagicMock()
        post_stopgame.id = "98765"
        post_stopgame.title = "Test Post StopGame"

        self.mock_pikabu.fetch_posts.return_value = [post_pikabu]
        self.mock_vgtimes.fetch_posts.return_value = [post_vgtimes]
        self.mock_stopgame.fetch_posts.return_value = [post_stopgame]

        posts = await self.manager.fetch_all_posts()
        self.assertEqual(len(posts), 3) 
        
        # Verify calls
        self.mock_pikabu.fetch_posts.assert_called_once()
        self.mock_vgtimes.fetch_posts.assert_called_once()
        self.mock_stopgame.fetch_posts.assert_called_once()

    async def test_stream_posts(self):
        """Tests that ParserManager can stream posts from all configured parsers."""
        # Setup mock streams
        post_pikabu = MagicMock()
        post_pikabu.id = "12345"
        
        post_vgtimes = MagicMock()
        post_vgtimes.id = "67890"
        
        post_stopgame = MagicMock()
        post_stopgame.id = "98765"

        async def pikabu_stream():
            yield post_pikabu
            
        async def vgtimes_stream():
            yield post_vgtimes
            
        async def stopgame_stream():
            yield post_stopgame

        self.mock_pikabu.stream_posts.side_effect = pikabu_stream
        self.mock_vgtimes.stream_posts.side_effect = vgtimes_stream
        self.mock_stopgame.stream_posts.side_effect = stopgame_stream

        # We need to break the infinite loop in stream_posts
        # We can do this by raising an exception in asyncio.sleep or running it for a short time
        # Alternatively, since we are testing the logic, we can iterate manually if possible, 
        # but stream_posts is an infinite loop. 
        # Better approach for unit test: run for one cycle.
        
        # However, stream_posts has a while True loop. 
        # Let's mock asyncio.sleep to raise specialized exception to break loop
        with patch('asyncio.sleep', side_effect=InterruptedError):
            try:
                streamed_posts = []
                async for post in self.manager.stream_posts():
                    streamed_posts.append(post)
            except InterruptedError:
                pass
        
        self.assertEqual(len(streamed_posts), 3)
        post_ids = {p.id for p in streamed_posts}
        self.assertIn("12345", post_ids)
        self.assertIn("67890", post_ids)
        self.assertIn("98765", post_ids)

if __name__ == '__main__':
    unittest.main()
