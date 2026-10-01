"""Catalog of games already announced by the free-games monitor."""

from datetime import datetime
from typing import Optional

from src.common.logger import logger


class _FreeGamesMixin:
    """Table: free_games_catalog."""

    async def init_free_games_tables(self) -> None:
        """Create free_games_catalog table if it doesn't exist."""
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS free_games_catalog (
                id          TEXT PRIMARY KEY,
                platform    TEXT NOT NULL,
                name        TEXT,
                url         TEXT,
                image_url   TEXT,
                description TEXT,
                first_seen  TIMESTAMP,
                notified_at TIMESTAMP
            )"""
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_free_games_platform ON free_games_catalog(platform)"
        )
        await conn.commit()
        logger.info("Free games catalog tables initialized")

    async def get_free_game(self, gid: str) -> Optional[dict]:
        """Get a free game record by its composite id (platform:slug)."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT id, platform, name, url, image_url, description, first_seen, notified_at "
                "FROM free_games_catalog WHERE id = ?",
                (gid,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0], "platform": row[1], "name": row[2], "url": row[3],
                "image_url": row[4], "description": row[5],
                "first_seen": row[6], "notified_at": row[7],
            }
        except Exception as e:
            logger.error("Error getting free game %s: %s", gid, e, exc_info=True)
            return None

    async def upsert_free_game(self, gid: str, platform: str, game: dict, notified: bool) -> None:
        """Insert or update a free game record.

        Sets first_seen on first insert; sets notified_at when notified=True.
        """
        try:
            conn = await self._get_connection()
            now = datetime.now()
            await conn.execute(
                """INSERT INTO free_games_catalog (id, platform, name, url, image_url, description, first_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO NOTHING""",
                (gid, platform, game.get("name"), game.get("url"),
                 game.get("image_url"), game.get("description"), now),
            )
            if notified:
                await conn.execute(
                    "UPDATE free_games_catalog SET notified_at = ? WHERE id = ? AND notified_at IS NULL",
                    (now, gid),
                )
            await conn.commit()
        except Exception as e:
            logger.error("Error upserting free game %s: %s", gid, e, exc_info=True)
