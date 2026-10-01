"""Estates — one game event (a giveaway or a deal) gathered from every source.

Every post about the same event from any source (Pikabu, VGTimes, StopGame, monitors) is collected
into one estate and sent as ONE message. Late duplicates attach to an already sent estate, whose
message is then edited instead of a new one being posted.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from src.common.logger import logger
from src.storage import game_keys


class _EstatesMixin:
    """Tables: estates, estate_posts, estate_keys and failed_estates (dead letter queue)."""

    ESTATE_MATCH_WINDOW_DAYS = 7

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

    # ── Dead letter queue ─────────────────────────────────────────────────

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
