import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models.models import Post, PostMetadata
from src.storage.sqlite_storage import SQLiteStorage


def make_post(
    post_id="123",
    source="VGTimes",
    title="Half-Life 3 Free",
    store_links=None,
    game_info=None,
    images=None,
    tags=None,
    is_free=False,
):
    gi = game_info or {}
    if is_free and not gi:
        gi = {"steam": {"name": "HL3", "price": None, "original_price": None,
                        "discount_pct": 0, "genre": None, "metacritic": None,
                        "developer": None, "is_free": True}}
    return Post(
        id=post_id,
        title=title,
        link="https://vgtimes.ru/free/123-hl3.html",
        content="Some content",
        source=source,
        metadata=PostMetadata(
            store_links=store_links or {"steam": "https://store.steampowered.com/app/123/"},
            game_info=gi,
            images=images or ["https://example.com/img.jpg"],
            tags=tags or ["игры"],
            date=datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc),
            rating=150,
        ),
    )


class TestSQLiteStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = str(Path(__file__).parent / "test_news_bot.db")
        self.storage = SQLiteStorage(self.db_path)

    async def asyncTearDown(self):
        await self.storage.close()
        if Path(self.db_path).exists():
            os.remove(self.db_path)

    async def test_mark_as_processed_and_is_processed(self):
        post_id = "test_post_1"

        self.assertFalse(await self.storage.is_processed(post_id))

        await self.storage.mark_as_processed(post_id)

        self.assertTrue(await self.storage.is_processed(post_id))

        await self.storage.close()
        new_storage = SQLiteStorage(self.db_path)
        self.assertTrue(await new_storage.is_processed(post_id))
        await new_storage.close()

    async def test_mark_duplicate(self):
        post_id = "test_post_duplicate"
        await self.storage.mark_as_processed(post_id)
        await self.storage.mark_as_processed(post_id)  # Should not raise error
        self.assertTrue(await self.storage.is_processed(post_id))

    async def test_cache_populated_on_init(self):
        """Кэш должен загружаться из БД при первом подключении."""
        # Pre-populate DB
        await self.storage.mark_as_processed("existing_1")
        await self.storage.mark_as_processed("existing_2")
        await self.storage.close()

        # Create new instance — cache should be loaded from DB
        fresh_storage = SQLiteStorage(self.db_path)
        # Trigger connection
        await fresh_storage._get_connection()

        self.assertIn("existing_1", fresh_storage._cache)
        self.assertIn("existing_2", fresh_storage._cache)
        await fresh_storage.close()

    async def test_is_processed_uses_cache(self):
        """is_processed должен использовать кэш, не выполняя лишних SQL-запросов."""
        await self.storage.mark_as_processed("cached_post")

        # Directly verify cache contains the ID
        self.assertIn("cached_post", self.storage._cache)

        # is_processed should return True from cache
        result = await self.storage.is_processed("cached_post")
        self.assertTrue(result)

        # Unknown ID should not be in cache
        result_unknown = await self.storage.is_processed("unknown_post")
        self.assertFalse(result_unknown)


class TestPostsLog(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = str(Path(__file__).parent / "test_posts_log.db")
        self.storage = SQLiteStorage(self.db_path)

    async def asyncTearDown(self):
        await self.storage.close()
        if Path(self.db_path).exists():
            os.remove(self.db_path)

    async def test_save_post_sent(self):
        post = make_post()
        await self.storage.save_post(post, sent=True)

        conn = await self.storage._get_connection()
        async with conn.execute("SELECT id, source, title, sent, has_steam FROM posts") as cur:
            row = await cur.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "123")
        self.assertEqual(row[1], "VGTimes")
        self.assertEqual(row[2], "Half-Life 3 Free")
        self.assertEqual(row[3], 1)   # sent=True
        self.assertEqual(row[4], 1)   # has_steam=True

    async def test_save_post_not_sent(self):
        post = make_post(post_id="456")
        await self.storage.save_post(post, sent=False)

        conn = await self.storage._get_connection()
        async with conn.execute("SELECT sent FROM posts WHERE id='456'") as cur:
            row = await cur.fetchone()
        self.assertEqual(row[0], 0)

    async def test_save_post_is_free_flag(self):
        post = make_post(is_free=True)
        await self.storage.save_post(post, sent=True)

        conn = await self.storage._get_connection()
        async with conn.execute("SELECT is_free FROM posts WHERE id='123'") as cur:
            row = await cur.fetchone()
        self.assertEqual(row[0], 1)

    async def test_save_post_store_flags(self):
        post = make_post(store_links={
            "steam": "https://store.steampowered.com/app/1/",
            "gog": "https://www.gog.com/game/test",
        })
        await self.storage.save_post(post, sent=True)

        conn = await self.storage._get_connection()
        async with conn.execute("SELECT has_steam, has_egs, has_gog, has_itch FROM posts") as cur:
            row = await cur.fetchone()
        self.assertEqual(row[0], 1)  # has_steam
        self.assertEqual(row[1], 0)  # has_egs
        self.assertEqual(row[2], 1)  # has_gog
        self.assertEqual(row[3], 0)  # has_itch

    async def test_save_post_upsert_updates_sent(self):
        """Повторный save_post обновляет sent и game_info."""
        post = make_post()
        await self.storage.save_post(post, sent=False)
        await self.storage.save_post(post, sent=True)

        conn = await self.storage._get_connection()
        async with conn.execute("SELECT COUNT(*), sent FROM posts WHERE id='123'") as cur:
            row = await cur.fetchone()
        self.assertEqual(row[0], 1)   # только одна запись
        self.assertEqual(row[1], 1)   # sent обновлён

    async def test_get_posts_stats(self):
        await self.storage.save_post(make_post("1", source="VGTimes"), sent=True)
        await self.storage.save_post(make_post("2", source="VGTimes"), sent=True)
        await self.storage.save_post(make_post("3", source="Pikabu"), sent=False)
        await self.storage.save_post(make_post("4", source="Pikabu", is_free=True), sent=True)

        stats = await self.storage.get_posts_stats()

        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["sent"], 3)
        self.assertEqual(stats["is_free"], 1)
        self.assertEqual(stats["by_source"]["VGTimes"], 2)
        self.assertEqual(stats["by_source"]["Pikabu"], 2)
        self.assertEqual(stats["sent_by_source"]["VGTimes"], 2)
        self.assertEqual(stats["sent_by_source"]["Pikabu"], 1)

    async def test_get_posts_stats_empty(self):
        stats = await self.storage.get_posts_stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["sent"], 0)


class TestCleanupOldPosts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = str(Path(__file__).parent / "test_cleanup.db")
        self.storage = SQLiteStorage(self.db_path)

    async def asyncTearDown(self):
        await self.storage.close()
        if Path(self.db_path).exists():
            os.remove(self.db_path)

    async def _insert_old_post(self, post_id: str, days_ago: int):
        """Insert a sent post with sent_at = now - days_ago."""
        conn = await self.storage._get_connection()
        old_time = datetime.now() - timedelta(days=days_ago)
        await conn.execute(
            "INSERT OR IGNORE INTO posts "
            "(id, source, title, link, content, stores, game_info, images, "
            " post_date, rating, tags, has_steam, has_egs, has_gog, has_itch, is_free, sent, sent_at) "
            "VALUES (?, 'Test', 'T', 'http://x.com', '', '[]', '{}', '[]', NULL, NULL, '[]', 0, 0, 0, 0, 0, 1, ?)",
            (post_id, old_time),
        )
        await conn.commit()

    async def test_cleanup_removes_old_posts(self):
        await self._insert_old_post("old1", days_ago=100)
        await self._insert_old_post("old2", days_ago=95)
        await self._insert_old_post("new1", days_ago=5)

        deleted = await self.storage.cleanup_old_posts(retention_days=90)

        self.assertEqual(deleted, 2)
        conn = await self.storage._get_connection()
        async with conn.execute("SELECT COUNT(*) FROM posts") as cur:
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 1)

    async def test_cleanup_keeps_unsent_posts(self):
        """Не удаляет посты с sent=0 даже если старые."""
        conn = await self.storage._get_connection()
        old_time = datetime.now() - timedelta(days=100)
        await conn.execute(
            "INSERT OR IGNORE INTO posts "
            "(id, source, title, link, content, stores, game_info, images, "
            " post_date, rating, tags, has_steam, has_egs, has_gog, has_itch, is_free, sent, sent_at) "
            "VALUES ('unsent1', 'Test', 'T', 'http://x.com', '', '[]', '{}', '[]', NULL, NULL, '[]', 0, 0, 0, 0, 0, 0, ?)",
            (old_time,),
        )
        await conn.commit()

        deleted = await self.storage.cleanup_old_posts(retention_days=90)
        self.assertEqual(deleted, 0)


class TestGetRecentPosts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = str(Path(__file__).parent / "test_recent.db")
        self.storage = SQLiteStorage(self.db_path)

    async def asyncTearDown(self):
        await self.storage.close()
        if Path(self.db_path).exists():
            os.remove(self.db_path)

    async def test_get_recent_posts_returns_sent(self):
        post1 = make_post("p1", title="First Post")
        post2 = make_post("p2", title="Second Post", source="Pikabu")
        await self.storage.save_post(post1, sent=True)
        await self.storage.save_post(post2, sent=True)

        recent = await self.storage.get_recent_posts(limit=5)
        ids = [r["id"] for r in recent]
        self.assertIn("p1", ids)
        self.assertIn("p2", ids)

    async def test_get_recent_posts_limit(self):
        for i in range(6):
            await self.storage.save_post(make_post(str(i)), sent=True)

        recent = await self.storage.get_recent_posts(limit=3)
        self.assertEqual(len(recent), 3)

    async def test_get_recent_posts_excludes_unsent(self):
        await self.storage.save_post(make_post("sent1"), sent=True)
        await self.storage.save_post(make_post("unsent1"), sent=False)

        recent = await self.storage.get_recent_posts(limit=10)
        ids = [r["id"] for r in recent]
        self.assertIn("sent1", ids)
        self.assertNotIn("unsent1", ids)

    async def test_get_recent_posts_empty(self):
        recent = await self.storage.get_recent_posts()
        self.assertEqual(recent, [])


if __name__ == "__main__":
    unittest.main()
