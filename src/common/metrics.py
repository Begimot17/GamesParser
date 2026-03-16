"""Cycle metrics dataclass for GamesParser."""

from dataclasses import dataclass, field
from datetime import datetime

from src.common.logger import logger


@dataclass
class CycleMetrics:
    """Collects statistics for one parsing cycle."""

    cycle_start: datetime = field(default_factory=datetime.utcnow)
    posts_found: int = 0
    posts_sent: int = 0
    posts_skipped_processed: int = 0
    posts_failed_send: int = 0
    posts_no_store_links: int = 0
    posts_no_steam_link: int = 0
    posts_no_image: int = 0

    def log_summary(self) -> None:
        duration = (datetime.utcnow() - self.cycle_start).total_seconds()
        logger.info(
            "[Metrics] Cycle summary | found=%d sent=%d skipped=%d failed=%d "
            "no_stores=%d no_steam=%d no_image=%d | duration=%.1fs",
            self.posts_found,
            self.posts_sent,
            self.posts_skipped_processed,
            self.posts_failed_send,
            self.posts_no_store_links,
            self.posts_no_steam_link,
            self.posts_no_image,
            duration,
        )
