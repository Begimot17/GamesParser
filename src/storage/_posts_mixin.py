"""Processed-post ids and the posts log."""

import json
from datetime import datetime, timedelta
from typing import Optional

from src.common.logger import logger
from src.storage import game_keys


class _PostsMixin:
    """Tables: processed_posts (ids already handled) and posts (full log of parsed posts)."""

    _cache: set[str]

    async def _init_posts_tables(self, conn) -> None:
        """Create the processed-ids and posts-log tables and load the processed-ids cache."""
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS processed_posts (id TEXT PRIMARY KEY, processed_at TIMESTAMP)",
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS posts (
                id          TEXT NOT NULL,
                source      TEXT,
                title       TEXT,
                link        TEXT,
                content     TEXT,
                stores      TEXT,
                game_info   TEXT,
                images      TEXT,
                post_date   TEXT,
                rating      INTEGER,
                tags        TEXT,
                has_steam   INTEGER DEFAULT 0,
                has_egs     INTEGER DEFAULT 0,
                has_gog     INTEGER DEFAULT 0,
                has_itch    INTEGER DEFAULT 0,
                is_free     INTEGER DEFAULT 0,
                sent        INTEGER DEFAULT 0,
                sent_at     TIMESTAMP,
                PRIMARY KEY (id, source)
            )"""
        )
        await conn.commit()
        async with conn.execute("SELECT id FROM processed_posts") as cursor:
            self._cache = {row[0] for row in await cursor.fetchall()}
        logger.info("SQLiteStorage cache populated with %s processed ids", len(self._cache))

    async def mark_as_processed(self, post_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                "INSERT OR IGNORE INTO processed_posts (id, processed_at) VALUES (?, ?)",
                (post_id, datetime.now()),
            )
            await conn.commit()
            self._cache.add(post_id)
            logger.info("Marked post %s as processed (SQLite)", post_id)
        except Exception as e:
            logger.error("Error marking post %s as processed: %s", post_id, e, exc_info=True)

    async def is_processed(self, post_id: str) -> bool:
        try:
            await self._get_connection()
            return post_id in self._cache
        except Exception as e:
            logger.error("Error checking if post %s is processed: %s", post_id, e, exc_info=True)
            return False

    async def save_post(self, post, sent: bool) -> None:
        """Save full post data to the posts log table.

        Args:
            post: Post model instance.
            sent: True if the post was successfully sent to Telegram.
        """
        try:
            meta = post.metadata
            store_links: dict = (meta.store_links or {}) if meta else {}
            game_info: dict = (meta.game_info or {}) if meta else {}
            images: list = (meta.images or []) if meta else []
            tags: list = (meta.tags or []) if meta else []
            rating: Optional[int] = (meta.rating) if meta else None
            post_date: Optional[str] = (meta.date.isoformat() if meta and meta.date else None)

            stores_list = list(store_links.keys())

            is_free = game_keys.is_free_from_game_info(game_info)

            conn = await self._get_connection()
            await conn.execute(
                """INSERT INTO posts
                   (id, source, title, link, content, stores, game_info, images,
                    post_date, rating, tags,
                    has_steam, has_egs, has_gog, has_itch, is_free,
                    sent, sent_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id, source) DO UPDATE SET
                       game_info=excluded.game_info,
                       is_free=excluded.is_free,
                       sent=excluded.sent,
                       sent_at=excluded.sent_at""",
                (
                    post.id,
                    post.source,
                    post.title,
                    str(post.link),
                    post.content,
                    json.dumps(stores_list, ensure_ascii=False),
                    json.dumps(game_info, ensure_ascii=False),
                    json.dumps(images, ensure_ascii=False),
                    post_date,
                    rating,
                    json.dumps(tags, ensure_ascii=False),
                    int("steam" in store_links),
                    int("epicgames" in store_links),
                    int("gog" in store_links),
                    int("itch" in store_links),
                    int(is_free),
                    int(sent),
                    datetime.now() if sent else None,
                ),
            )
            await conn.commit()
        except Exception as e:
            logger.error("Error saving post %s to posts log: %s", post.id, e, exc_info=True)

    async def get_posts_stats(self) -> dict:
        """Return aggregate statistics from the posts log."""
        try:
            conn = await self._get_connection()
            stats: dict = {}

            async with conn.execute("SELECT COUNT(*) FROM posts") as cur:
                stats["total"] = (await cur.fetchone())[0]

            async with conn.execute("SELECT COUNT(*) FROM posts WHERE sent=1") as cur:
                stats["sent"] = (await cur.fetchone())[0]

            async with conn.execute("SELECT COUNT(*) FROM posts WHERE is_free=1") as cur:
                stats["is_free"] = (await cur.fetchone())[0]

            async with conn.execute(
                "SELECT source, COUNT(*) FROM posts GROUP BY source ORDER BY COUNT(*) DESC"
            ) as cur:
                stats["by_source"] = {row[0]: row[1] for row in await cur.fetchall()}

            async with conn.execute(
                "SELECT source, COUNT(*) FROM posts WHERE sent=1 GROUP BY source ORDER BY COUNT(*) DESC"
            ) as cur:
                stats["sent_by_source"] = {row[0]: row[1] for row in await cur.fetchall()}

            return stats
        except Exception as e:
            logger.error("Error getting posts stats: %s", e, exc_info=True)
            return {}

    async def get_recent_posts(self, limit: int = 5) -> list[dict]:
        """Return recently sent posts (newest first)."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT id, source, title, link, sent_at FROM posts"
                " WHERE sent=1 ORDER BY sent_at DESC LIMIT ?",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
            return [
                {"id": r[0], "source": r[1], "title": r[2], "link": r[3], "sent_at": r[4]}
                for r in rows
            ]
        except Exception as e:
            logger.error("Error getting recent posts: %s", e, exc_info=True)
            return []

    async def cleanup_old_posts(self, retention_days: int) -> int:
        """Delete sent posts older than retention_days. Returns number of deleted rows."""
        try:
            conn = await self._get_connection()
            cutoff = datetime.now() - timedelta(days=retention_days)
            async with conn.execute(
                "DELETE FROM posts WHERE sent_at < ? AND sent = 1",
                (cutoff,),
            ) as cur:
                deleted = cur.rowcount
            await conn.commit()
            return deleted
        except Exception as e:
            logger.error("Error cleaning up old posts: %s", e, exc_info=True)
            return 0
