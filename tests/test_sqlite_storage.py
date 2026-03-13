import os
import unittest
from pathlib import Path

from src.storage.sqlite_storage import SQLiteStorage


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


if __name__ == "__main__":
    unittest.main()
