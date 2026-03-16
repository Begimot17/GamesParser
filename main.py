import asyncio
import json
import logging
import sys
from datetime import date, datetime

from src.bot.bot import TelegramNewsBot
from src.common.logger import setup_logger, logger, audit_logger, missing_data_logger
from src.common.metrics import CycleMetrics
from src.config.config import settings
from src.models.models import Post
from src.parsers.parser_manager import ParserManager
from src.parsers.pikabu_parser import PikabuParser
from src.parsers.stopgame_parser import StopGameParser
from src.parsers.vgtimes_parser import VGTimesParser
from src.storage.sqlite_storage import SQLiteStorage
from typing import Optional


class NewsMonitor:
    """Main class for monitoring news sources."""

    def __init__(self):
        self.settings = settings

        self.storage = SQLiteStorage(self.settings.DB_PATH)
        self._last_cleanup: Optional[date] = None
        self.bot = TelegramNewsBot(
            token=self.settings.TELEGRAM_BOT_TOKEN,
            channel_id=self.settings.TELEGRAM_CHANNEL_ID
        )

        parsers = [
            PikabuParser(),
            VGTimesParser(),
            StopGameParser(),
        ]
        self.parsers = parsers
        self.parser_manager = ParserManager(parsers=parsers, storage=self.storage)

    async def run(self, use_streaming: bool = True):
        """Runs the monitoring loop."""
        logger.info("Starting NewsMonitor...")
        try:
            if use_streaming:
                from src.bot.command_handler import CommandHandler
                cmd_handler = CommandHandler(self.storage, self)
                self.bot.register_commands(cmd_handler)
                await asyncio.gather(
                    self._run_streaming(),
                    self.bot.start_polling(),
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
        """Runs the monitoring loop using streaming."""
        logger.info("Starting streaming mode...")
        async for post in self.parser_manager.stream_posts():
            # Daily cleanup of old posts
            today = date.today()
            if self._last_cleanup != today:
                try:
                    deleted = await self.storage.cleanup_old_posts(self.settings.DB_RETENTION_DAYS)
                    if deleted:
                        logger.info("[Cleanup] Removed %d old posts (retention=%dd)", deleted, self.settings.DB_RETENTION_DAYS)
                except Exception as e:
                    logger.error("[Cleanup] Failed: %s", e)
                self._last_cleanup = today

            metrics = CycleMetrics()
            try:
                metrics.posts_found += 1

                if await self.storage.is_processed(post.id):
                    metrics.posts_skipped_processed += 1
                    continue

                # Title deduplication
                seen, orig_id, orig_source = await self.storage.is_title_seen(post.title)
                if seen:
                    missing_data_logger.info(
                        "[Dedup] Duplicate title skipped: %s (original: %s/%s)",
                        post.id, orig_source, orig_id
                    )
                    metrics.posts_skipped_processed += 1
                    continue

                # Track metrics for missing data
                if post.metadata:
                    if not post.metadata.store_links:
                        metrics.posts_no_store_links += 1
                    elif "steam" not in post.metadata.store_links:
                        metrics.posts_no_steam_link += 1
                    if not post.metadata.images:
                        metrics.posts_no_image += 1

                logger.info(f"New post found: {post.title} ({post.link})")
                success = await self.bot.send_message(
                    self.bot.formatter.format_message(post),
                    images=self._safe_images(post)
                )

                await self.storage.save_post(post, sent=success)

                if success:
                    await self.storage.mark_as_processed(post.id)
                    await self.storage.mark_title_seen(post.title, post.id, post.source)
                    self._audit_post(post, success=True)
                    metrics.posts_sent += 1
                    logger.info(f"Post {post.id} processed and sent.")
                else:
                    metrics.posts_failed_send += 1
                    self._audit_post(post, success=False)
                    logger.error(f"Failed to send post {post.id}")
                    # Save to DLQ
                    try:
                        await self.storage.save_failed_post(
                            post.id, post.model_dump_json(), "send_message returned False"
                        )
                    except Exception as dlq_err:
                        logger.error("[DLQ] Failed to save post %s: %s", post.id, dlq_err)

                await asyncio.sleep(self.settings.STREAM_POST_PROCESSING_DELAY)

            except Exception as e:
                logger.error(f"Error processing post in stream: {e}", exc_info=True)
            finally:
                metrics.log_summary()

        await self._retry_failed_posts()

    async def _run_polling(self):
        """Runs the monitoring loop using polling (legacy)."""
        logger.info("Starting polling mode...")
        while True:
            try:
                posts = await self.parser_manager.fetch_all_posts()
                for post in posts:
                    if await self.storage.is_processed(post.id):
                        continue

                    logger.info(f"New post found: {post.title}")
                    success = await self.bot.send_message(
                        self.bot.formatter.format_message(post),
                        images=self._safe_images(post)
                    )

                    if success:
                        await self.storage.mark_as_processed(post.id)

                    await asyncio.sleep(self.settings.POST_PROCESSING_DELAY)

                logger.info(f"Sleeping for {self.settings.CHECK_INTERVAL} seconds...")
                await asyncio.sleep(self.settings.CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(self.settings.CHECK_INTERVAL)


def main() -> None:
    """Entry point."""
    try:
        monitor = NewsMonitor()
        asyncio.run(monitor.run(use_streaming=True))
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
