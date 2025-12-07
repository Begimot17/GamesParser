import unittest
import aiosqlite
import asyncio
from pathlib import Path
from src.storage.sqlite_storage import SQLiteStorage
import os

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
        
        # Initially not processed
        self.assertFalse(await self.storage.is_processed(post_id))
        
        # Mark as processed
        await self.storage.mark_as_processed(post_id)
        
        # Now processed
        self.assertTrue(await self.storage.is_processed(post_id))
        
        # Check persistence (re-open storage? SQLiteStorage connects on demand/cached)
        # Let's create another instance
        await self.storage.close()
        new_storage = SQLiteStorage(self.db_path)
        self.assertTrue(await new_storage.is_processed(post_id))
        await new_storage.close()

    async def test_mark_duplicate(self):
        post_id = "test_post_duplicate"
        await self.storage.mark_as_processed(post_id)
        await self.storage.mark_as_processed(post_id) # Should not raise error
        self.assertTrue(await self.storage.is_processed(post_id))

if __name__ == "__main__":
    unittest.main()
