import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.parsers.parser_manager import ParserManager


class TestParserManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_pikabu = MagicMock()
        self.mock_pikabu.__class__.__name__ = "PikabuParser"

        self.mock_vgtimes = MagicMock()
        self.mock_vgtimes.__class__.__name__ = "VGTimesParser"

        self.mock_stopgame = MagicMock()
        self.mock_stopgame.__class__.__name__ = "StopGameParser"

        self.mock_pikabu.__aenter__ = AsyncMock(return_value=self.mock_pikabu)
        self.mock_pikabu.__aexit__ = AsyncMock(return_value=None)

        self.mock_vgtimes.__aenter__ = AsyncMock(return_value=self.mock_vgtimes)
        self.mock_vgtimes.__aexit__ = AsyncMock(return_value=None)

        self.mock_stopgame.__aenter__ = AsyncMock(return_value=self.mock_stopgame)
        self.mock_stopgame.__aexit__ = AsyncMock(return_value=None)

        self.mock_pikabu.fetch_posts = AsyncMock()
        self.mock_vgtimes.fetch_posts = AsyncMock()
        self.mock_stopgame.fetch_posts = AsyncMock()

        self.mock_storage = AsyncMock()
        self.mock_storage.is_processed = AsyncMock(return_value=False)
        self.mock_storage.get_posts_stats = AsyncMock(return_value={"total": 1})

        self.parsers = [self.mock_vgtimes, self.mock_pikabu, self.mock_stopgame]
        self.manager = ParserManager(parsers=self.parsers, storage=self.mock_storage)

    async def test_fetch_all_posts(self):
        """Tests that ParserManager can fetch posts from all configured parsers."""
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

        self.mock_pikabu.fetch_posts.assert_called_once()
        self.mock_vgtimes.fetch_posts.assert_called_once()
        self.mock_stopgame.fetch_posts.assert_called_once()

    async def test_fetch_all_posts_one_parser_fails(self):
        """При падении одного парсера результаты других сохраняются."""
        post_vgtimes = MagicMock()
        post_vgtimes.id = "67890"

        post_stopgame = MagicMock()
        post_stopgame.id = "98765"

        self.mock_pikabu.fetch_posts.side_effect = RuntimeError("Network error")
        self.mock_vgtimes.fetch_posts.return_value = [post_vgtimes]
        self.mock_stopgame.fetch_posts.return_value = [post_stopgame]

        posts = await self.manager.fetch_all_posts()
        # pikabu fails, but vgtimes and stopgame results are kept
        self.assertEqual(len(posts), 2)
        post_ids = {p.id for p in posts}
        self.assertIn("67890", post_ids)
        self.assertIn("98765", post_ids)

    async def test_fetch_all_posts_skips_processed(self):
        """fetch_all_posts фильтрует уже обработанные посты через storage."""
        post1 = MagicMock()
        post1.id = "new_post"
        post2 = MagicMock()
        post2.id = "old_post"

        self.mock_pikabu.fetch_posts.return_value = [post1, post2]
        self.mock_vgtimes.fetch_posts.return_value = []
        self.mock_stopgame.fetch_posts.return_value = []

        async def is_processed_side_effect(post_id):
            return post_id == "old_post"

        self.mock_storage.is_processed = AsyncMock(side_effect=is_processed_side_effect)

        posts = await self.manager.fetch_all_posts()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].id, "new_post")

    async def test_stream_posts(self):
        """Tests that ParserManager can stream posts from all configured parsers."""
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

        # No storage — no filtering
        self.manager.storage = None

        with patch("asyncio.sleep", side_effect=InterruptedError):
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

    async def test_stream_posts_skips_processed(self):
        """stream_posts пропускает посты, уже обработанные в storage."""
        new_post = MagicMock()
        new_post.id = "new_post"
        old_post = MagicMock()
        old_post.id = "old_post"

        async def parser_stream():
            yield new_post
            yield old_post

        self.mock_pikabu.stream_posts.side_effect = parser_stream
        self.mock_vgtimes.stream_posts.side_effect = lambda: (_ for _ in ())
        self.mock_stopgame.stream_posts.side_effect = lambda: (_ for _ in ())

        async def is_processed_side_effect(post_id):
            return post_id == "old_post"

        self.mock_storage.is_processed = AsyncMock(side_effect=is_processed_side_effect)

        with patch("asyncio.sleep", side_effect=InterruptedError):
            try:
                streamed_posts = []
                async for post in self.manager.stream_posts():
                    streamed_posts.append(post)
            except InterruptedError:
                pass

        self.assertEqual(len(streamed_posts), 1)
        self.assertEqual(streamed_posts[0].id, "new_post")


if __name__ == "__main__":
    unittest.main()
