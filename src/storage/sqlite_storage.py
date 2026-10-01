"""SQLite storage implementation for GamesParser."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from src.common.logger import logger
from src.storage import game_keys
from src.storage.base import Storage

# Words to strip when normalising titles for fuzzy deduplication
_NOISE_WORDS = re.compile(
    r"\b(бесплатн\w*|free|раздача|стала|тепер|now|"
    r"навсегда|forever|тимчасово|temporarily|неделю|"
    r"giveaways?|"                            # "Havendock (Epic Games) Giveaway" → "Havendock"
    r"epic\s+games?\s+store|epic\s+games?)\b",  # "[Epic Games Store]" prefix
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
            await self.init_estate_tables()
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
            logger.info("SQLiteStorage cache populated with %s entries, %s title hashes", len(self._cache), len(self._title_cache))
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

    # ── Title deduplication ──────────────────────────────────────────────

    @staticmethod
    def _is_free_from_game_info(game_info_map: dict) -> bool:
        """Return True if any entry in game_info_map marks the game as free."""
        for raw in game_info_map.values():
            if isinstance(raw, dict) and raw.get("is_free"):
                return True
            if isinstance(raw, list) and any(isinstance(r, dict) and r.get("is_free") for r in raw):
                return True
        return False

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
                logger.error("Error checking title dedup (hash): %s", e, exc_info=True)
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
                logger.error("Error checking title dedup (normalized): %s", e, exc_info=True)

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
            logger.error("Error marking title seen: %s", e, exc_info=True)

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
            logger.error("Error saving failed post %s: %s", post_id, e, exc_info=True)

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
            logger.error("Error getting failed posts: %s", e, exc_info=True)
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
            logger.error("Error incrementing retry for %s: %s", post_id, e, exc_info=True)

    async def delete_failed_post(self, post_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute("DELETE FROM failed_posts WHERE id = ?", (post_id,))
            await conn.commit()
        except Exception as e:
            logger.error("Error deleting failed post %s: %s", post_id, e, exc_info=True)

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

            is_free = self._is_free_from_game_info(game_info)

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
        """Create egs_catalog table if it doesn't exist, and run inline migrations."""
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS egs_catalog (
                url_slug           TEXT PRIMARY KEY,
                name               TEXT,
                url                TEXT,
                price_uah          INTEGER,
                original_price_uah INTEGER,
                discount_pct       INTEGER DEFAULT 0,
                last_checked       TIMESTAMP,
                notified_price_uah INTEGER,
                notified_at        TIMESTAMP,
                key_image          TEXT,
                description        TEXT
            )"""
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_egs_name ON egs_catalog(lower(trim(name)))"
        )
        await conn.commit()

        # Inline migrations: rename old USD columns → UAH (idempotent via try/except)
        for sql in [
            "ALTER TABLE egs_catalog RENAME COLUMN price_usd TO price_uah",
            "ALTER TABLE egs_catalog RENAME COLUMN original_price_usd TO original_price_uah",
            "ALTER TABLE egs_catalog RENAME COLUMN notified_price_usd TO notified_price_uah",
        ]:
            try:
                await conn.execute(sql)
                await conn.commit()
            except Exception:
                pass  # Column already renamed or doesn't exist

        # Add new columns if missing
        for sql in [
            "ALTER TABLE egs_catalog ADD COLUMN key_image TEXT",
            "ALTER TABLE egs_catalog ADD COLUMN description TEXT",
        ]:
            try:
                await conn.execute(sql)
                await conn.commit()
            except Exception:
                pass  # Column already exists

        logger.info("EGS catalog tables initialized")

    async def get_egs_game(self, url_slug: str) -> Optional[dict]:
        """Get a single EGS game record by url_slug."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT url_slug, name, url, price_uah, original_price_uah, discount_pct, "
                "last_checked, notified_price_uah, notified_at, key_image, description "
                "FROM egs_catalog WHERE url_slug = ?",
                (url_slug,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "url_slug": row[0], "name": row[1], "url": row[2],
                "price_uah": row[3], "original_price_uah": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_uah": row[7], "notified_at": row[8],
                "key_image": row[9], "description": row[10],
            }
        except Exception as e:
            logger.error("Error getting EGS game %s: %s", url_slug, e, exc_info=True)
            return None

    async def upsert_egs_games(self, games: list[dict]) -> None:
        """Batch upsert EGS game records."""
        if not games:
            return
        try:
            conn = await self._get_connection()
            await conn.executemany(
                """INSERT INTO egs_catalog
                   (url_slug, name, url, price_uah, original_price_uah, discount_pct,
                    key_image, description, last_checked)
                   VALUES (:url_slug, :name, :url, :price_uah, :original_price_uah, :discount_pct,
                    :key_image, :description, :last_checked)
                   ON CONFLICT(url_slug) DO UPDATE SET
                       name=COALESCE(excluded.name, egs_catalog.name),
                       url=excluded.url,
                       price_uah=excluded.price_uah,
                       original_price_uah=COALESCE(excluded.original_price_uah, egs_catalog.original_price_uah),
                       discount_pct=excluded.discount_pct,
                       key_image=COALESCE(excluded.key_image, egs_catalog.key_image),
                       description=COALESCE(excluded.description, egs_catalog.description),
                       last_checked=excluded.last_checked""",
                games,
            )
            await conn.commit()
        except Exception as e:
            logger.error("Error upserting EGS games: %s", e, exc_info=True)

    async def update_egs_notification(self, url_slug: str, price_uah: int) -> None:
        """Record that a notification was sent for an EGS game at a given price."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE egs_catalog SET notified_price_uah = ?, notified_at = ? WHERE url_slug = ?",
                (price_uah, datetime.now(), url_slug),
            )
            await conn.commit()
        except Exception as e:
            logger.error("Error updating EGS notification for %s: %s", url_slug, e, exc_info=True)

    async def find_egs_game_by_name(self, name: str) -> Optional[dict]:
        """Find an EGS game by case-insensitive trimmed name match."""
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT url_slug, name, url, price_uah, original_price_uah, discount_pct, "
                "last_checked, notified_price_uah, notified_at, key_image, description "
                "FROM egs_catalog WHERE lower(trim(name)) = lower(trim(?))",
                (name,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return {
                "url_slug": row[0], "name": row[1], "url": row[2],
                "price_uah": row[3], "original_price_uah": row[4],
                "discount_pct": row[5], "last_checked": row[6],
                "notified_price_uah": row[7], "notified_at": row[8],
                "key_image": row[9], "description": row[10],
            }
        except Exception as e:
            logger.error("Error finding EGS game by name %s: %s", repr(name), e, exc_info=True)
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
            logger.error("Error finding Steam game by name %s: %s", repr(name), e, exc_info=True)
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
            logger.error("Error getting steam game %s: %s", appid, e, exc_info=True)
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
            logger.error("Error upserting steam games: %s", e, exc_info=True)

    async def get_steam_appids(self) -> list[int]:
        """Return all appids stored in steam_catalog."""
        try:
            conn = await self._get_connection()
            async with conn.execute("SELECT appid FROM steam_catalog") as cursor:
                rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error("Error getting steam appids: %s", e, exc_info=True)
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
            logger.error("Error updating steam notification for %s: %s", appid, e, exc_info=True)

    # ── Free Games Catalog ────────────────────────────────────────────────

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

    # ── Estate ───────────────────────────────────────────────────────────
    #
    # An estate is one game event (a giveaway or a deal) — every post about it from any source
    # (Pikabu, VGTimes, StopGame, monitors) is collected into one estate and sent as ONE message.
    # Late duplicates attach to an already-sent estate and the sent message is edited instead.

    ESTATE_MATCH_WINDOW_DAYS = 7
    # Whose description wins when several sources describe the same event
    _SOURCE_RANK = {"VGTimes": 3, "StopGame": 2, "Pikabu": 1}

    _ESTATE_COLUMNS = (
        "estate_id, title, kind, is_free, description, images, tags, games, "
        "message_id, message_is_caption, alert_sent, needs_edit, created_at"
    )

    async def init_estate_tables(self) -> None:
        """Create estate tables if they don't exist and migrate old schemas."""
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS estates (
                estate_id        TEXT PRIMARY KEY,
                title            TEXT NOT NULL,
                title_normalized TEXT,
                store_url        TEXT,
                store_name       TEXT,
                is_free          INTEGER DEFAULT 0,
                description      TEXT,
                images           TEXT,
                tags             TEXT,
                created_at       TIMESTAMP NOT NULL,
                flushed_at       TIMESTAMP,
                alert_sent       INTEGER DEFAULT 0
            )"""
        )
        migrations = {
            "title_normalized": "TEXT",
            "kind": "TEXT",
            "games": "TEXT",
            "description_rank": "INTEGER DEFAULT 0",
            "message_id": "INTEGER",
            "message_is_caption": "INTEGER DEFAULT 0",
            "needs_edit": "INTEGER DEFAULT 0",
        }
        async with conn.execute("PRAGMA table_info(estates)") as cursor:
            existing_cols = {row[1] for row in await cursor.fetchall()}
        for col, col_type in migrations.items():
            if col not in existing_cols:
                await conn.execute(f"ALTER TABLE estates ADD COLUMN {col} {col_type}")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS estate_posts (
                estate_id  TEXT NOT NULL,
                post_id    TEXT NOT NULL,
                source     TEXT NOT NULL,
                post_link  TEXT NOT NULL,
                added_at   TIMESTAMP NOT NULL,
                PRIMARY KEY (estate_id, post_id, source)
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS estate_keys (
                estate_id TEXT NOT NULL,
                key       TEXT NOT NULL,
                PRIMARY KEY (estate_id, key)
            )"""
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_estate_keys_key ON estate_keys(key)")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS failed_estates (
                estate_id   TEXT PRIMARY KEY,
                estate_json TEXT NOT NULL,
                failed_at   TIMESTAMP,
                retry_count INTEGER DEFAULT 0,
                last_error  TEXT
            )"""
        )
        await conn.commit()
        await self._backfill_estate_keys(conn)

    async def _backfill_estate_keys(self, conn) -> None:
        """Give recent pre-migration estates identity keys so new posts can match them."""
        cutoff = datetime.now() - timedelta(days=self.ESTATE_MATCH_WINDOW_DAYS)
        async with conn.execute(
            "SELECT estate_id, title, store_name, store_url, is_free FROM estates "
            "WHERE created_at >= ? AND kind IS NULL",
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()
        for estate_id, title, store_name, store_url, is_free in rows:
            links = {store_name: [store_url]} if store_name and store_url else {}
            games = game_keys.games_from_links(links)
            keys = game_keys.estate_keys(title, games)
            kind = game_keys.event_kind(bool(is_free) or game_keys.looks_like_giveaway(title), title)
            await conn.execute(
                "UPDATE estates SET kind=?, games=?, title_normalized=? WHERE estate_id=?",
                (kind, json.dumps(games, ensure_ascii=False), game_keys.compact(title), estate_id),
            )
            await conn.executemany(
                "INSERT OR IGNORE INTO estate_keys (estate_id, key) VALUES (?, ?)",
                [(estate_id, k) for k in keys],
            )
        if rows:
            await conn.commit()
            logger.info("[Estate] Backfilled identity keys for %d recent estates", len(rows))

    async def find_matching_estate(self, keys: set[str], title: str, kind: str) -> Optional[str]:
        """Return the newest estate (sent or not, within the match window) describing the same event.

        Match = same kind AND (shared store/name key OR one side's game name appears in the other's headline).
        """
        cutoff = datetime.now() - timedelta(days=self.ESTATE_MATCH_WINDOW_DAYS)
        try:
            conn = await self._get_connection()
            if keys:
                placeholders = ",".join("?" * len(keys))
                async with conn.execute(
                    f"SELECT e.estate_id FROM estate_keys k JOIN estates e ON e.estate_id = k.estate_id "
                    f"WHERE k.key IN ({placeholders}) AND e.kind = ? AND e.created_at >= ? "
                    f"ORDER BY e.created_at DESC LIMIT 1",
                    (*keys, kind, cutoff),
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    return row[0]

            # Fuzzy: a game name of one side is contained in the other side's headline
            min_len = game_keys.MIN_SUBSTRING_LEN
            new_names = {k[5:] for k in keys if k.startswith("name:") and len(k) - 5 >= min_len}
            new_title = game_keys.compact(title)
            async with conn.execute(
                "SELECT e.estate_id, e.title_normalized, group_concat(k.key, '|') FROM estates e "
                "LEFT JOIN estate_keys k ON k.estate_id = e.estate_id AND k.key LIKE 'name:%' "
                "WHERE e.kind = ? AND e.created_at >= ? GROUP BY e.estate_id ORDER BY e.created_at DESC",
                (kind, cutoff),
            ) as cursor:
                rows = await cursor.fetchall()
            for estate_id, old_title, old_keys in rows:
                old_names = {k[5:] for k in (old_keys or "").split("|") if len(k) - 5 >= min_len}
                if any(n in (old_title or "") for n in new_names) or any(n in new_title for n in old_names):
                    return estate_id
            return None
        except Exception as e:
            logger.error("[Estate] find_matching_estate error: %s", e, exc_info=True)
            return None

    async def upsert_estate(
        self,
        estate_id: str,
        title: str,
        *,
        kind: str,
        is_free: bool,
        description: str = "",
        source: Optional[str] = None,
        images: Optional[list] = None,
        tags: Optional[list] = None,
        games: Optional[list] = None,
        keys: Optional[set] = None,
    ) -> bool:
        """Insert or merge data into an estate. Returns True if the estate was already sent
        (the sent message should then be edited rather than a new one sent)."""
        images = [str(i) for i in (images or [])]
        tags = [str(t) for t in (tags or [])]
        games = games or []
        rank = self._SOURCE_RANK.get(source or "", 0)
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT is_free, description, description_rank, images, tags, games, alert_sent "
                "FROM estates WHERE estate_id=?",
                (estate_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            already_sent = False
            if existing:
                ex_free, ex_desc, ex_rank, ex_images, ex_tags, ex_games, alert_sent = existing
                already_sent = bool(alert_sent)
                ex_rank = ex_rank or 0
                if description and (rank > ex_rank or not ex_desc):
                    final_desc, final_rank = description, rank
                else:
                    final_desc, final_rank = ex_desc or "", ex_rank
                merged_games = game_keys.merge_games(json.loads(ex_games or "[]"), games)
                await conn.execute(
                    """UPDATE estates SET is_free=?, description=?, description_rank=?, images=?, tags=?,
                           games=?, needs_edit=CASE WHEN alert_sent=1 THEN 1 ELSE needs_edit END
                       WHERE estate_id=?""",
                    (
                        max(int(ex_free or 0), int(is_free)), final_desc, final_rank,
                        json.dumps(list(dict.fromkeys(json.loads(ex_images or "[]") + images)), ensure_ascii=False),
                        json.dumps(list(dict.fromkeys(json.loads(ex_tags or "[]") + tags)), ensure_ascii=False),
                        json.dumps(merged_games, ensure_ascii=False),
                        estate_id,
                    ),
                )
            else:
                await conn.execute(
                    """INSERT INTO estates
                           (estate_id, title, title_normalized, kind, is_free, description, description_rank,
                            images, tags, games, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        estate_id, title, game_keys.compact(title), kind, int(is_free), description, rank,
                        json.dumps(images, ensure_ascii=False), json.dumps(tags, ensure_ascii=False),
                        json.dumps(game_keys.merge_games([], games), ensure_ascii=False), datetime.now(),
                    ),
                )
            if keys:
                await conn.executemany(
                    "INSERT OR IGNORE INTO estate_keys (estate_id, key) VALUES (?, ?)",
                    [(estate_id, k) for k in keys],
                )
            await conn.commit()
            logger.debug("[Estate] Upserted estate %s for title: %s", estate_id[:8], title)
            return already_sent
        except Exception as e:
            logger.error("[Estate] Error upserting estate %s: %s", estate_id[:8], e, exc_info=True)
            return False

    async def add_post_to_estate(self, estate_id: str, post) -> None:
        """Register a post as part of an estate (idempotent)."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                """INSERT OR IGNORE INTO estate_posts (estate_id, post_id, source, post_link, added_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (estate_id, post.id, post.source or "", str(post.link), datetime.now()),
            )
            await conn.commit()
        except Exception as e:
            logger.error("[Estate] Error adding post %s to estate %s: %s", post.id, estate_id[:8], e, exc_info=True)

    async def _load_estates(self, where: str, params: tuple = ()) -> list[dict]:
        conn = await self._get_connection()
        async with conn.execute(f"SELECT {self._ESTATE_COLUMNS} FROM estates WHERE {where}", params) as cursor:
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            (estate_id, title, kind, is_free, description, images_json, tags_json, games_json,
             message_id, message_is_caption, alert_sent, needs_edit, created_at) = row
            async with conn.execute(
                "SELECT ep.post_id, ep.source, ep.post_link, p.title FROM estate_posts ep "
                "LEFT JOIN posts p ON p.id = ep.post_id AND p.source = ep.source "
                "WHERE ep.estate_id=? ORDER BY ep.added_at",
                (estate_id,),
            ) as cursor:
                post_rows = await cursor.fetchall()
            result.append({
                "estate_id": estate_id,
                "title": title,
                "kind": kind or "",
                "is_free": bool(is_free),
                "description": description or "",
                "images": json.loads(images_json or "[]"),
                "tags": json.loads(tags_json or "[]"),
                "games": json.loads(games_json or "[]"),
                "posts": [
                    {"post_id": r[0], "source": r[1], "post_link": r[2], "title": r[3] or ""} for r in post_rows
                ],
                "message_id": message_id,
                "message_is_caption": bool(message_is_caption),
                "alert_sent": bool(alert_sent),
                "needs_edit": bool(needs_edit),
                "created_at": created_at,
            })
        return result

    async def get_estate(self, estate_id: str) -> Optional[dict]:
        try:
            estates = await self._load_estates("estate_id=?", (estate_id,))
            return estates[0] if estates else None
        except Exception as e:
            logger.error("[Estate] Error loading estate %s: %s", estate_id[:8], e, exc_info=True)
            return None

    async def get_pending_estates(self) -> list[dict]:
        """Return all estates not yet flushed, with their associated posts."""
        try:
            return await self._load_estates("flushed_at IS NULL AND alert_sent=0 ORDER BY created_at")
        except Exception as e:
            logger.error("[Estate] Error getting pending estates: %s", e, exc_info=True)
            return []

    async def get_estates_to_edit(self) -> list[dict]:
        """Return sent estates that received new posts after their message was sent."""
        try:
            return await self._load_estates("alert_sent=1 AND needs_edit=1")
        except Exception as e:
            logger.error("[Estate] Error getting estates to edit: %s", e, exc_info=True)
            return []

    async def mark_estate_flushed(
        self, estate_id: str, sent: bool, message_id: Optional[int] = None, is_caption: bool = False,
    ) -> None:
        """Mark an estate as flushed (processed this cycle), remembering the sent message for later edits."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE estates SET flushed_at=?, alert_sent=?, needs_edit=0, "
                "message_id=COALESCE(?, message_id), message_is_caption=? WHERE estate_id=?",
                (datetime.now(), int(sent), message_id, int(is_caption), estate_id),
            )
            await conn.commit()
        except Exception as e:
            logger.error("[Estate] Error marking estate flushed %s: %s", estate_id[:8], e, exc_info=True)

    async def clear_estate_edit(self, estate_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute("UPDATE estates SET needs_edit=0 WHERE estate_id=?", (estate_id,))
            await conn.commit()
        except Exception as e:
            logger.error("[Estate] Error clearing edit flag %s: %s", estate_id[:8], e, exc_info=True)

    async def mark_posts_sent(self, estate_id: str) -> None:
        """Mark all posts belonging to an estate as sent in the posts log."""
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE posts SET sent=1, sent_at=COALESCE(sent_at, ?) "
                "WHERE (id, source) IN (SELECT post_id, source FROM estate_posts WHERE estate_id=?)",
                (datetime.now(), estate_id),
            )
            await conn.commit()
        except Exception as e:
            logger.error("[Estate] Error marking posts sent for estate %s: %s", estate_id[:8], e, exc_info=True)

    # ── Estate DLQ ────────────────────────────────────────────────────────

    async def save_failed_estate(self, estate_id: str, estate_json: str, error: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                """INSERT INTO failed_estates (estate_id, estate_json, failed_at, retry_count, last_error)
                   VALUES (?, ?, ?, 0, ?)
                   ON CONFLICT(estate_id) DO UPDATE SET
                       last_error=excluded.last_error, failed_at=excluded.failed_at""",
                (estate_id, estate_json, datetime.now(), error),
            )
            await conn.commit()
        except Exception as e:
            logger.error("[Estate DLQ] Error saving failed estate %s: %s", estate_id[:8], e, exc_info=True)

    async def get_failed_estates(self, max_retries: int = 3) -> list[dict]:
        try:
            conn = await self._get_connection()
            async with conn.execute(
                "SELECT estate_id, estate_json, retry_count FROM failed_estates WHERE retry_count < ?",
                (max_retries,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [{"estate_id": r[0], "estate_json": r[1], "retry_count": r[2]} for r in rows]
        except Exception as e:
            logger.error("[Estate DLQ] Error getting failed estates: %s", e, exc_info=True)
            return []

    async def delete_failed_estate(self, estate_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute("DELETE FROM failed_estates WHERE estate_id=?", (estate_id,))
            await conn.commit()
        except Exception as e:
            logger.error("[Estate DLQ] Error deleting failed estate %s: %s", estate_id[:8], e, exc_info=True)

    async def increment_estate_retry(self, estate_id: str) -> None:
        try:
            conn = await self._get_connection()
            await conn.execute(
                "UPDATE failed_estates SET retry_count = retry_count + 1 WHERE estate_id=?",
                (estate_id,),
            )
            await conn.commit()
        except Exception as e:
            logger.error("[Estate DLQ] Error incrementing retry for estate %s: %s", estate_id[:8], e, exc_info=True)

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("SQLite storage connection closed")
