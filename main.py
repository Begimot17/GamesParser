import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import date, datetime

from src.bot.bot import SentMessage, TelegramNewsBot
from src.common.logger import setup_logger, logger, audit_logger, missing_data_logger
from src.common.metrics import CycleMetrics
from src.config.config import settings
from src.config.run_config import is_parser_enabled, is_monitor_enabled, get_monitor_interval
from src.models.models import Post
from src.monitors.egs_price_monitor import EgsPriceMonitor
from src.monitors.free_games_monitor import FreeGamesMonitor
from src.monitors.steam_price_monitor import SteamPriceMonitor
from src.services.gamerpower_service import GamerPowerService
from src.services.gog_free_games_service import GogFreeGamesService
from src.services.indiegala_free_games_service import IndieGalaFreeGamesService
from src.services.price_service import PriceService
from src.parsers.parser_manager import ParserManager
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.stopgame_parser import StopGameParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.storage import game_keys
from src.storage.sqlite_storage import SQLiteStorage
from typing import Optional


class NewsMonitor:
    """Main class for monitoring news sources."""

    def __init__(self):
        self.settings = settings

        self.storage = SQLiteStorage(self.settings.DB_PATH)
        self._last_cleanup: Optional[date] = None
        self._price_service = PriceService()
        self.bot = TelegramNewsBot(
            token=self.settings.TELEGRAM_BOT_TOKEN,
            channel_id=self.settings.TELEGRAM_CHANNEL_ID
        )

        all_parsers = [
            ("pikabu", PikabuParser),
            ("vgtimes", VGTimesParser),
            ("stopgame", StopGameParser),
        ]
        parsers = [cls() for name, cls in all_parsers if is_parser_enabled(name)]
        self.parsers = parsers
        self.parser_manager = ParserManager(parsers=parsers, storage=self.storage)
        monitors = []
        if is_monitor_enabled("steam"):
            steam_cfg = settings.MONITORS_CONFIG.get("steam", {})
            monitors.append(SteamPriceMonitor(
                storage=self.storage,
                bot=self.bot,
                scan_interval=get_monitor_interval("steam", default=43200),
                specials_only=bool(steam_cfg.get("specials_only", True)),
            ))
        if is_monitor_enabled("egs"):
            monitors.append(EgsPriceMonitor(
                storage=self.storage,
                bot=self.bot,
                scan_interval=get_monitor_interval("egs", default=43200),
            ))
        if is_monitor_enabled("free_games"):
            free_cfg = settings.MONITORS_CONFIG.get("free_games", {})
            svc_cfg = free_cfg.get("services", {})
            services = []
            if svc_cfg.get("gog", True):
                services.append(GogFreeGamesService())
            if svc_cfg.get("indiegala", True):
                services.append(IndieGalaFreeGamesService())
            if svc_cfg.get("gamerpower", True):
                services.append(GamerPowerService())
            if services:
                monitors.append(FreeGamesMonitor(
                    storage=self.storage,
                    bot=self.bot,
                    scan_interval=get_monitor_interval("free_games", default=3600),
                    services=services,
                ))
        self.monitors = monitors

    async def run(self, use_streaming: bool = True):
        """Runs the monitoring loop."""
        logger.info("Starting NewsMonitor...")
        await self.storage.init_estate_tables()
        try:
            if use_streaming:
                from src.bot.command_handler import CommandHandler
                cmd_handler = CommandHandler(self.storage, self)
                self.bot.register_commands(cmd_handler)
                await asyncio.gather(
                    self._run_streaming(),
                    self.bot.start_polling(),
                    *[m.run() for m in self.monitors],
                )
            else:
                await self._run_polling()
        except KeyboardInterrupt:
            logger.info("NewsMonitor stopped by user.")
        finally:
            await self.storage.close()
            await self.bot.close()

    def _safe_images(self, post: Post) -> list[str]:
        """Filter images to only https:// URLs."""
        images = post.metadata.images if post.metadata else []
        if not images:
            return []
        safe = [img for img in images if isinstance(img, str) and img.startswith("https://")]
        filtered = len(images) - len(safe)
        if filtered > 0:
            missing_data_logger.warning(
                "[Bot] Filtered %d non-https images for post %s", filtered, post.id
            )
        return safe

    def _audit_post(self, post: Post, success: bool) -> None:
        """Write audit log entry for a sent post."""
        store_keys = list(post.metadata.store_links.keys()) if post.metadata and post.metadata.store_links else []
        audit_logger.info(json.dumps({
            "ts": datetime.utcnow().isoformat(),
            "post_id": post.id,
            "source": post.source,
            "title": post.title,
            "channel": self.settings.TELEGRAM_CHANNEL_ID,
            "stores": store_keys,
            "sent": success,
        }, ensure_ascii=False))

    async def _add_post_to_estate(self, post: Post) -> None:
        """Accumulate a post into the estate of its game event.

        Posts from different sources about the same game (same store link, same game name, or a game
        name found in the other headline) land in one estate. If that estate was already sent,
        the sent message gets edited on the next flush instead of a duplicate being posted.
        """
        meta = post.metadata
        games = game_keys.games_from_links(meta.store_links or {}, meta.game_info or {}) if meta else []
        game_keys.apply_title_names(games, post.title)
        is_free = (
            SQLiteStorage._is_free_from_game_info((meta.game_info or {}) if meta else {})
            or game_keys.looks_like_giveaway(post.title)
        )
        kind = game_keys.event_kind(is_free, post.title)
        keys = game_keys.estate_keys(post.title, games)

        estate_id = await self.storage.find_matching_estate(keys, post.title, kind)
        if estate_id:
            logger.info("[Estate] Post %s (%s) joins existing estate %s", post.id, post.source, estate_id[:8])
        else:
            estate_id = uuid.uuid4().hex
            logger.info("[Estate] Post %s (%s) opens new estate %s", post.id, post.source, estate_id[:8])

        already_sent = await self.storage.upsert_estate(
            estate_id,
            post.title,
            kind=kind,
            is_free=is_free,
            description=post.content or "",
            source=post.source,
            images=self._safe_images(post),
            tags=(meta.tags or []) if meta else [],
            games=games,
            keys=keys,
        )
        await self.storage.add_post_to_estate(estate_id, post)
        await self.storage.save_post(post, sent=False)
        await self.storage.mark_title_seen(post.title, post.id, post.source)
        await self.storage.mark_as_processed(post.id)
        if already_sent:
            logger.info("[Estate] Estate %s was already sent — its message will be updated", estate_id[:8])

    async def _enrich_with_steam(self, estate: dict):
        """Fetch fresh Steam GameInfo for a single-game estate with a Steam link."""
        games = estate.get("games") or []
        if len(games) != 1:
            return None
        url = games[0].get("links", {}).get("steam", "")
        if not re.search(r"/app/\d+", url):
            return None
        try:
            return await self._price_service.get_steam_info(url, lang="russian")
        except Exception as e:
            logger.warning("[Estate] Steam enrichment failed for %s: %s", url, e)
            return None

    async def _render_estate(self, estate: dict) -> tuple[str, list[str]]:
        """Return (caption, images) for an estate."""
        game_info = await self._enrich_with_steam(estate)
        text = self.bot.formatter.format_estate_alert(estate, game_info=game_info)
        images: list[str] = [i for i in estate.get("images", []) if isinstance(i, str) and i.startswith("https://")]
        if game_info and getattr(game_info, "header_image", None):
            images = [game_info.header_image] + images
        return text, images[:1]

    async def _send_estate(self, estate: dict) -> Optional[SentMessage]:
        """Format and send one estate alert. Returns the sent message reference or None."""
        text, images = await self._render_estate(estate)
        return await self.bot.send_message(text, images=images or None)

    async def _update_sent_estate(self, estate: dict) -> None:
        """A late post joined an already sent estate: edit that message to include it."""
        estate_id = estate["estate_id"]
        if estate.get("message_id"):
            text, _ = await self._render_estate(estate)
            ref = SentMessage(estate["message_id"], is_caption=estate.get("message_is_caption", False))
            if await self.bot.edit_message(ref, text):
                logger.info("[Estate] Updated sent estate %s with new sources", estate_id[:8])
        else:
            logger.info("[Estate] Estate %s was sent before message tracking — duplicate suppressed", estate_id[:8])
        await self.storage.clear_estate_edit(estate_id)
        await self.storage.mark_posts_sent(estate_id)

    async def _flush_pending_estates(self) -> None:
        """Send one Telegram alert per pending estate, then mark them flushed.
        Sent estates that received late posts get their message edited."""
        estates = await self.storage.get_pending_estates()
        if estates:
            logger.info("[Estate] Flushing %d estate(s)...", len(estates))
        for estate in estates:
            try:
                ref = await self._send_estate(estate)
                await self.storage.mark_estate_flushed(
                    estate["estate_id"],
                    sent=bool(ref),
                    message_id=getattr(ref, "message_id", None),
                    is_caption=getattr(ref, "is_caption", False),
                )
                if ref:
                    await self.storage.mark_posts_sent(estate["estate_id"])
                    logger.info("[Estate] Sent estate %s: %s", estate["estate_id"][:8], estate["title"])
                else:
                    logger.error("[Estate] Failed to send estate %s", estate["estate_id"][:8])
                    await self.storage.save_failed_estate(
                        estate["estate_id"],
                        json.dumps(estate, default=str),
                        "send_message returned no message",
                    )
            except Exception as e:
                logger.error("[Estate] Error flushing estate %s: %s", estate["estate_id"][:8], e, exc_info=True)
                try:
                    await self.storage.mark_estate_flushed(estate["estate_id"], sent=False)
                    await self.storage.save_failed_estate(
                        estate["estate_id"], json.dumps(estate, default=str), str(e)
                    )
                except Exception:
                    pass
            await asyncio.sleep(self.settings.STREAM_POST_PROCESSING_DELAY)

        for estate in await self.storage.get_estates_to_edit():
            try:
                await self._update_sent_estate(estate)
            except Exception as e:
                logger.error("[Estate] Error updating estate %s: %s", estate["estate_id"][:8], e, exc_info=True)

    async def _retry_failed_estates(self) -> None:
        """Attempt to resend estates from the Dead Letter Queue."""
        failed = await self.storage.get_failed_estates(max_retries=3)
        if not failed:
            return
        logger.info("[Estate DLQ] Retrying %d failed estate(s)", len(failed))
        for entry in failed:
            estate_id = entry["estate_id"]
            try:
                # Prefer the current DB state: posts may have joined the estate since it failed
                estate = await self.storage.get_estate(estate_id) or json.loads(entry["estate_json"])
                ref = await self._send_estate(estate)
                if ref:
                    await self.storage.mark_estate_flushed(
                        estate_id, sent=True, message_id=ref.message_id, is_caption=ref.is_caption,
                    )
                    await self.storage.mark_posts_sent(estate_id)
                    await self.storage.delete_failed_estate(estate_id)
                    logger.info("[Estate DLQ] Retry succeeded for estate %s", estate_id[:8])
                else:
                    await self.storage.increment_estate_retry(estate_id)
                    logger.warning("[Estate DLQ] Retry failed for estate %s", estate_id[:8])
            except Exception as e:
                logger.error("[Estate DLQ] Error retrying estate %s: %s", estate_id[:8], e, exc_info=True)
                await self.storage.increment_estate_retry(estate_id)

    async def _retry_failed_posts(self) -> None:
        """Attempt to resend posts from the Dead Letter Queue."""
        failed = await self.storage.get_failed_posts(max_retries=3)
        if not failed:
            return
        logger.info("[DLQ] Retrying %d failed posts", len(failed))
        for entry in failed:
            post_id = entry["id"]
            try:
                post_data = json.loads(entry["post_json"])
                from src.models.models import Post as PostModel
                post = PostModel.model_validate(post_data)
                success = await self.bot.send_message(
                    self.bot.formatter.format_message(post),
                    images=self._safe_images(post)
                )
                if success:
                    await self.storage.mark_as_processed(post_id)
                    await self.storage.delete_failed_post(post_id)
                    self._audit_post(post, success=True)
                    logger.info("[DLQ] Retry succeeded for post %s", post_id)
                else:
                    await self.storage.increment_retry(post_id)
                    logger.warning("[DLQ] Retry failed for post %s", post_id)
            except Exception as e:
                logger.error("[DLQ] Error retrying post %s: %s", post_id, e, exc_info=True)
                await self.storage.increment_retry(post_id)

    async def _run_streaming(self):
        """Runs the monitoring loop using streaming with estate-based grouping."""
        logger.info("Starting streaming mode...")
        async for item in self.parser_manager.stream_posts():
            if item is None:
                # End-of-cycle sentinel: flush estates, retry DLQs, daily cleanup
                today = date.today()
                if self._last_cleanup != today:
                    try:
                        deleted = await self.storage.cleanup_old_posts(self.settings.DB_RETENTION_DAYS)
                        if deleted:
                            logger.info("[Cleanup] Removed %d old posts (retention=%dd)", deleted, self.settings.DB_RETENTION_DAYS)
                    except Exception as e:
                        logger.error("[Cleanup] Failed: %s", e)
                    self._last_cleanup = today

                await self._flush_pending_estates()
                await self._retry_failed_estates()
                await self._retry_failed_posts()
                continue

            post: Post = item
            try:
                if await self.storage.is_processed(post.id):
                    continue

                await self._add_post_to_estate(post)
                await asyncio.sleep(self.settings.STREAM_POST_PROCESSING_DELAY)
            except Exception as e:
                logger.error("Error accumulating post %s into estate: %s", post.id, e, exc_info=True)

    async def _run_polling(self):
        """Runs the monitoring loop using polling (legacy)."""
        logger.info("Starting polling mode...")
        while True:
            try:
                posts = await self.parser_manager.fetch_all_posts()
                for post in posts:
                    if await self.storage.is_processed(post.id):
                        continue

                    logger.info("New post found: %s", post.title)
                    success = await self.bot.send_message(
                        self.bot.formatter.format_message(post),
                        images=self._safe_images(post)
                    )

                    if success:
                        await self.storage.mark_as_processed(post.id)

                    await asyncio.sleep(self.settings.POST_PROCESSING_DELAY)

                logger.info("Sleeping for %s seconds...", self.settings.CHECK_INTERVAL)
                await asyncio.sleep(self.settings.CHECK_INTERVAL)

            except Exception as e:
                logger.error("Error in polling loop: %s", e, exc_info=True)
                await asyncio.sleep(self.settings.CHECK_INTERVAL)


def main() -> None:
    """Entry point."""
    try:
        monitor = NewsMonitor()
        asyncio.run(monitor.run(use_streaming=True))
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
