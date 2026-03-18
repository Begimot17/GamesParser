"""Shared base for Steam and EGS price monitors."""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, Optional

from src.bot.bot import TelegramNewsBot
from src.bot.message_formatter import MessageFormatter
from src.common.logger import logger
from src.storage.sqlite_storage import SQLiteStorage


class PriceMonitorBase(ABC):
    """Abstract base with shared run-loop and alert-dispatch logic."""

    LOG_PREFIX: ClassVar[str]

    def __init__(self, storage: SQLiteStorage, bot: TelegramNewsBot, scan_interval: Optional[int] = None):
        self.storage = storage
        self.bot = bot
        self.formatter = MessageFormatter()
        self._scan_interval = scan_interval

    @abstractmethod
    async def _init_store_tables(self) -> None:
        """Initialise store-specific DB tables."""

    @abstractmethod
    async def _run_cycle(self) -> None:
        """Execute a single scan cycle."""

    def _get_scan_interval(self) -> int:
        """Return the configured scan interval in seconds."""
        if self._scan_interval is not None:
            return self._scan_interval
        raise NotImplementedError("scan_interval must be set via constructor or _get_scan_interval override")

    # ── Shared run loop ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop: initialise tables, then repeatedly run cycles."""
        interval = self._get_scan_interval()
        logger.info("[%s] Starting price monitor (interval=%ds)", self.LOG_PREFIX, interval)
        await self._init_store_tables()
        while True:
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error("[%s] Cycle error: %s", self.LOG_PREFIX, e, exc_info=True)
            logger.info("[%s] Sleeping for %d seconds until next scan", self.LOG_PREFIX, interval)
            await asyncio.sleep(interval)

    # ── Shared helpers ────────────────────────────────────────────────────

    async def _dispatch_alert(
        self,
        display_name: str,
        url: str,
        stored: dict,
        new_price: int,
        new_original: Optional[int],
        new_discount: int,
        alert_type: str,
        game_info,
        images: Optional[list],
        short_description: Optional[str],
        cross_store_data: Optional[dict],
        store: str,
    ) -> bool:
        """Format and send a price-change alert. Returns True if sent successfully."""
        message = self.formatter.format_price_alert(
            name=display_name,
            url=url,
            old_price_uah=stored.get("price_uah"),
            new_price_uah=new_price,
            original_price_uah=new_original,
            discount_pct=new_discount,
            alert_type=alert_type,
            game_info=game_info,
            store=store,
            cross_store_data=cross_store_data,
            short_description=short_description,
        )
        return await self.bot.send_message(message, images=images)

    @staticmethod
    def _extract_cross_store_row(row: Optional[dict], store: str) -> Optional[dict]:
        """Return cross-store data dict if the row was notified within the last 30 minutes."""
        if not row or not row.get("notified_at"):
            return None
        try:
            notified_dt = datetime.fromisoformat(row["notified_at"])
        except (ValueError, TypeError):
            return None
        if (datetime.now() - notified_dt).total_seconds() >= 1800:
            return None
        return {
            "store": store,
            "url": row.get("url", ""),
            "price_uah": row.get("price_uah"),
            "original_price_uah": row.get("original_price_uah"),
            "discount_pct": row.get("discount_pct"),
        }

    @staticmethod
    def _detect_change(
        stored: dict,
        new_price: int,
        new_original: Optional[int],
        new_discount: int,
        discount_threshold: int,
    ) -> Optional[str]:
        """Return alert type ('became_free' | 'big_discount') or None.

        Rules:
        - Alert only when the price CHANGED compared to the stored price.
        - Never re-alert at the same price that was already notified.
        """
        if new_original is None:
            return None

        stored_price = stored.get("price_uah")
        notified_price = stored.get("notified_price_uah")

        if stored_price is not None and stored_price == new_price:
            return None

        if new_original > 0 and new_price == 0:
            return "became_free" if notified_price != new_price else None

        if new_discount >= discount_threshold and new_original > 0:
            return "big_discount" if notified_price != new_price else None

        return None
