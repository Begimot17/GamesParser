"""SQLite storage for GamesParser.

The storage is split by domain into mixins; this class owns the connection and schema setup.
"""

import aiosqlite

from src.common.logger import logger
from src.storage._catalog_mixin import _CatalogMixin
from src.storage._estates_mixin import _EstatesMixin
from src.storage._free_games_mixin import _FreeGamesMixin
from src.storage._posts_mixin import _PostsMixin
from src.storage.base import Storage


class SQLiteStorage(_PostsMixin, _EstatesMixin, _CatalogMixin, _FreeGamesMixin, Storage):
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self._connection = None
        self._cache: set[str] = set()

    async def _get_connection(self):
        if not self._connection:
            self._connection = await aiosqlite.connect(self.db_path)
            await self._init_posts_tables(self._connection)
            await self.init_estate_tables()
        return self._connection

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("SQLite storage connection closed")
