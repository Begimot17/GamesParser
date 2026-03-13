"""SQLite storage implementation for GamesParser."""

from datetime import datetime

import aiosqlite

from src.common.logger import logger
from src.storage.base import Storage


class SQLiteStorage(Storage):
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self._connection = None
        self._cache: set[str] = set()

    async def _get_connection(self):
        if not self._connection:
            self._connection = await aiosqlite.connect(self.db_path)
            await self._connection.execute(
                "CREATE TABLE IF NOT EXISTS processed_posts (id TEXT PRIMARY KEY, processed_at TIMESTAMP)",
            )
            await self._connection.commit()
            # Populate cache from DB on first connect
            async with self._connection.execute("SELECT id FROM processed_posts") as cursor:
                rows = await cursor.fetchall()
                self._cache = {row[0] for row in rows}
            logger.info(f"SQLiteStorage cache populated with {len(self._cache)} entries")
        return self._connection

    async def mark_as_processed(self, post_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                "INSERT OR IGNORE INTO processed_posts (id, processed_at) VALUES (?, ?)",
                (post_id, datetime.now()),
            )
            await conn.commit()
            self._cache.add(post_id)
            logger.info(f"Marked post {post_id} as processed (SQLite)")
        except Exception as e:
            logger.error(f"Error marking post {post_id} as processed: {e}", exc_info=True)

    async def is_processed(self, post_id: str) -> bool:
        try:
            # Check cache first (requires connection to be established)
            await self._get_connection()
            return post_id in self._cache
        except Exception as e:
            logger.error(f"Error checking if post {post_id} is processed: {e}", exc_info=True)
            return False

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("SQLite storage connection closed")
