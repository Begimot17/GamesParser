"""SQLite storage implementation for GamesParser."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from src.common.logger import logger
from src.storage.base import Storage

# Words to strip when normalising titles for fuzzy deduplication
_NOISE_WORDS = re.compile(
    r"\b(бесплатн\w*|free|раздача|стала|тепер|now|"
    r"навсегда|forever|тимчасово|temporarily|неделю)\b",
    re.IGNORECASE | re.UNICODE,
)


class SQLiteStorage(Storage):
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self._connection = None
        self._cache: set[str] = set()
        self._title_cache: set[str] = set()

    async def _get_connection(self):
        if not self._connection:
            self._connection = await aiosqlite.connect(self.db_path)
            await self._connection.execute(
                "CREATE TABLE IF NOT EXISTS processed_posts (id TEXT PRIMARY KEY, processed_at TIMESTAMP)",
            )
            await self._connection.execute(
                """CREATE TABLE IF NOT EXISTS failed_posts (
                    id TEXT PRIMARY KEY,
                    post_json TEXT NOT NULL,
                    failed_at TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT
                )"""
            )
            await self._connection.execute(
                """CREATE TABLE IF NOT EXISTS post_titles (
                    title_hash TEXT PRIMARY KEY,
                    post_id TEXT,
                    source TEXT,
                    seen_at TIMESTAMP
                )"""
            )
            await self._connection.execute(
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
            await self._connection.commit()
            # Migrate: add title_normalized column if missing
            try:
                await self._connection.execute(
                    "ALTER TABLE post_titles ADD COLUMN title_normalized TEXT"
                )
                await self._connection.commit()
            except Exception:
                pass  # Column already exists
            await self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_title_norm ON post_titles(title_normalized)"
            )
            await self._connection.commit()
            # Populate caches from DB on first connect
            async with self._connection.execute("SELECT id FROM processed_posts") as cursor:
                rows = await cursor.fetchall()
                self._cache = {row[0] for row in rows}
            async with self._connection.execute("SELECT title_hash FROM post_titles") as cursor:
                rows = await cursor.fetchall()
                self._title_cache = {row[0] for row in rows}
            logger.info(f"SQLiteStorage cache populated with {len(self._cache)} entries, {len(self._title_cache)} title hashes")
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
            await self._get_connection()
            return post_id in self._cache
        except Exception as e:
            logger.error(f"Error checking if post {post_id} is processed: {e}", exc_info=True)
            return False

    # ── Title deduplication ──────────────────────────────────────────────

    @staticmethod
    def _title_hash(title: str) -> str:
        return hashlib.sha256(title.lower().strip().encode()).hexdigest()

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for fuzzy deduplication: lowercase, strip noise words and punctuation."""
        t = title.lower().strip()
        t = _NOISE_WORDS.sub("", t)
        t = re.sub(r"[^\w\u0400-\u04FF\s]", "", t)
        return re.sub(r"\s+", " ", t).strip()

    async def is_title_seen(self, title: str) -> tuple[bool, str, str]:
        """Check if a title was seen by exact hash or fuzzy normalized match.

        Returns (seen, original_post_id, original_source).
        """
        h = self._title_hash(title)
        n = self._normalize_title(title)

        # Fast in-memory check by exact hash
        if h in self._title_cache:
            try:
                conn = await self._get_connection()
                async with conn.execute(
                    "SELECT post_id, source FROM post_titles WHERE title_hash = ?", (h,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    return True, row[0], row[1]
            except Exception as e:
                logger.error(f"Error checking title dedup (hash): {e}", exc_info=True)
            return True, "", ""

        # Fuzzy check by normalized title (catches near-duplicates from different sources)
        if n:
            try:
                conn = await self._get_connection()
                async with conn.execute(
                    "SELECT post_id, source FROM post_titles WHERE title_normalized = ?", (n,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    return True, row[0], row[1]
            except Exception as e:
                logger.error(f"Error checking title dedup (normalized): {e}", exc_info=True)

        return False, "", ""

    async def mark_title_seen(self, title: str, post_id: str, source: str) -> None:
        h = self._title_hash(title)
        n = self._normalize_title(title)
        try:
            conn = await self._get_connection()
            await conn.execute(
                "INSERT OR IGNORE INTO post_titles "
                "(title_hash, post_id, source, seen_at, title_normalized) VALUES (?, ?, ?, ?, ?)",
                (h, post_id, source, datetime.now(), n),
            )
            await conn.commit()
            self._title_cache.add(h)
        except Exception as e:
            logger.error(f"Error marking title seen: {e}", exc_info=True)

    # ── Dead Letter Queue ────────────────────────────────────────────────

    async def save_failed_post(self, post_id: str, post_json: str, error: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                """INSERT INTO failed_posts (id, post_json, failed_at, retry_count, last_error)
                   VALUES (?, ?, ?, 0, ?)
                   ON CONFLICT(id) DO UPDATE SET last_error=excluded.last_error, failed_at=excluded.failed_at""",
                (post_id, post_json, datetime.now(), error),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error saving failed post {post_id}: {e}", exc_info=True)

    async def get_failed_posts(self, max_retries: int = 3) -> list[dict]:
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT id, post_json, retry_count FROM failed_posts WHERE retry_count < ?",
                (max_retries,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [{"id": r[0], "post_json": r[1], "retry_count": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"Error getting failed posts: {e}", exc_info=True)
            return []

    async def increment_retry(self, post_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE failed_posts SET retry_count = retry_count + 1 WHERE id = ?",
                (post_id,),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing retry for {post_id}: {e}", exc_info=True)

    async def delete_failed_post(self, post_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute("DELETE FROM failed_posts WHERE id = ?", (post_id,))
            await conn.commit()
        except Exception as e:
            logger.error(f"Error deleting failed post {post_id}: {e}", exc_info=True)

    # ── Posts log ────────────────────────────────────────────────────────

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

            # Determine is_free from any GameInfo
            is_free = False
            for raw in game_info.values():
                if isinstance(raw, dict) and raw.get("is_free"):
                    is_free = True
                    break
                if isinstance(raw, list):
                    if any(isinstance(r, dict) and r.get("is_free") for r in raw):
                        is_free = True
                        break

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
            logger.error(f"Error saving post {post.id} to posts log: {e}", exc_info=True)

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
            logger.error(f"Error getting posts stats: {e}", exc_info=True)
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
            logger.error(f"Error getting recent posts: {e}", exc_info=True)
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
            logger.error(f"Error cleaning up old posts: {e}", exc_info=True)
            return 0

    # ── Steam Catalog ─────────────────────────────────────────────────────

    async def init_steam_tables(self) -> None:
        """Create steam_catalog table if it doesn't exist."""
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS steam_catalog (
                appid              INTEGER PRIMARY KEY,
                name               TEXT,
                url                TEXT,
                price_uah          INTEGER,
                original_price_uah INTEGER,
                discount_pct       INTEGER DEFAULT 0,
                last_checked       TIMESTAMP,
                notified_price_uah INTEGER,
                notified_at        TIMESTAMP
            )"""
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_steam_last_checked ON steam_catalog(last_checked)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_steam_name ON steam_catalog(lower(trim(name)))"
        )
        await conn.commit()
        logger.info("Steam catalog tables initialized")

    async def init_egs_tables(self) -> None:
        """Create egs_catalog table if it doesn't exist."""
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS egs_catalog (
                url_slug           TEXT PRIMARY KEY,
                name               TEXT,
                url                TEXT,
                price_usd          INTEGER,
                original_price_usd INTEGER,
                discount_pct       INTEGER DEFAULT 0,
                last_checked       TIMESTAMP,
                notified_price_usd INTEGER,
                notified_at        TIMESTAMP
            )"""
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_egs_name ON egs_catalog(lower(trim(name)))"
        )
        await conn.commit()
        logger.info("EGS catalog tables initialized")

    async def get_egs_game(self, url_slug: str) -> Optional[dict]:
        """Get a single EGS game record by url_slug."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT url_slug, name, url, price_usd, original_price_usd, discount_pct, "
                "last_checked, notified_price_usd, notified_at FROM egs_catalog WHERE url_slug = ?",
                (url_slug,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "url_slug": row[0], "name": row[1], "url": row[2],
                "price_usd": row[3], "original_price_usd": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_usd": row[7], "notified_at": row[8],
            }
        except Exception as e:
            logger.error(f"Error getting EGS game {url_slug}: {e}", exc_info=True)
            return None

    async def upsert_egs_games(self, games: list[dict]) -> None:
        """Batch upsert EGS game records."""
        if not games:
            return
        try:
            conn = await self._get_connection()
            await conn.executemany(
                """INSERT INTO egs_catalog
                   (url_slug, name, url, price_usd, original_price_usd, discount_pct, last_checked)
                   VALUES (:url_slug, :name, :url, :price_usd, :original_price_usd, :discount_pct, :last_checked)
                   ON CONFLICT(url_slug) DO UPDATE SET
                       name=COALESCE(excluded.name, egs_catalog.name),
                       url=excluded.url,
                       price_usd=excluded.price_usd,
                       original_price_usd=COALESCE(excluded.original_price_usd, egs_catalog.original_price_usd),
                       discount_pct=excluded.discount_pct,
                       last_checked=excluded.last_checked""",
                games,
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error upserting EGS games: {e}", exc_info=True)

    async def update_egs_notification(self, url_slug: str, price_usd: int) -> None:
        """Record that a notification was sent for an EGS game at a given price."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE egs_catalog SET notified_price_usd = ?, notified_at = ? WHERE url_slug = ?",
                (price_usd, datetime.now(), url_slug),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error updating EGS notification for {url_slug}: {e}", exc_info=True)

    async def find_egs_game_by_name(self, name: str) -> Optional[dict]:
        """Find an EGS game by case-insensitive trimmed name match."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT url_slug, name, url, price_usd, original_price_usd, discount_pct, "
                "last_checked, notified_price_usd, notified_at FROM egs_catalog "
                "WHERE lower(trim(name)) = lower(trim(?))",
                (name,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "url_slug": row[0], "name": row[1], "url": row[2],
                "price_usd": row[3], "original_price_usd": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_usd": row[7], "notified_at": row[8],
            }
        except Exception as e:
            logger.error(f"Error finding EGS game by name {name!r}: {e}", exc_info=True)
            return None

    async def find_steam_game_by_name(self, name: str) -> Optional[dict]:
        """Find a Steam game by case-insensitive trimmed name match."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT appid, name, url, price_uah, original_price_uah, discount_pct, "
                "last_checked, notified_price_uah, notified_at FROM steam_catalog "
                "WHERE lower(trim(name)) = lower(trim(?))",
                (name,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "appid": row[0], "name": row[1], "url": row[2],
                "price_uah": row[3], "original_price_uah": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_uah": row[7], "notified_at": row[8],
            }
        except Exception as e:
            logger.error(f"Error finding Steam game by name {name!r}: {e}", exc_info=True)
            return None

    async def get_steam_game(self, appid: int) -> Optional[dict]:
        """Get a single steam game record by appid."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT appid, name, url, price_uah, original_price_uah, discount_pct, "
                "last_checked, notified_price_uah, notified_at FROM steam_catalog WHERE appid = ?",
                (appid,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "appid": row[0], "name": row[1], "url": row[2],
                "price_uah": row[3], "original_price_uah": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_uah": row[7], "notified_at": row[8],
            }
        except Exception as e:
            logger.error(f"Error getting steam game {appid}: {e}", exc_info=True)
            return None

    async def upsert_steam_games(self, games: list[dict]) -> None:
        """Batch upsert steam game records."""
        if not games:
            return
        try:
            conn = await self._get_connection()
            await conn.executemany(
                """INSERT INTO steam_catalog
                   (appid, name, url, price_uah, original_price_uah, discount_pct, last_checked)
                   VALUES (:appid, :name, :url, :price_uah, :original_price_uah, :discount_pct, :last_checked)
                   ON CONFLICT(appid) DO UPDATE SET
                       name=COALESCE(excluded.name, steam_catalog.name),
                       price_uah=excluded.price_uah,
                       original_price_uah=COALESCE(excluded.original_price_uah, steam_catalog.original_price_uah),
                       discount_pct=excluded.discount_pct,
                       last_checked=excluded.last_checked""",
                games,
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error upserting steam games: {e}", exc_info=True)

    async def get_steam_appids(self) -> list[int]:
        """Return all appids stored in steam_catalog."""
        try:
            conn = await self._get_connection()
            async with conn.execute("SELECT appid FROM steam_catalog") as cursor:
                rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting steam appids: {e}", exc_info=True)
            return []

    async def update_steam_notification(self, appid: int, price_uah: int) -> None:
        """Record that a notification was sent for a game at a given price."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE steam_catalog SET notified_price_uah = ?, notified_at = ? WHERE appid = ?",
                (price_uah, datetime.now(), appid),
            )
            await conn.commit()
        except Exception as e:
            logger.error(f"Error updating steam notification for {appid}: {e}", exc_info=True)

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("SQLite storage connection closed")
