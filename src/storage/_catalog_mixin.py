"""Steam and EGS price catalogs used by the price monitors."""

from datetime import datetime
from typing import Optional

from src.common.logger import logger


class _CatalogMixin:
    """Tables: steam_catalog and egs_catalog."""

    # ── Steam ─────────────────────────────────────────────────────────────

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

    # ── EGS ───────────────────────────────────────────────────────────────

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
