"""Shared base for Steam and EGS price monitors."""

import asyncio
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, Optional

from src.bot.bot import TelegramNewsBot
from src.bot.message_formatter import MessageFormatter
from src.common.logger import logger
from src.storage import game_keys
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
        worth: Optional[str] = None,
        kind_hint: str = "",
    ) -> bool:
        """Format and send a price-change alert. Returns True if sent (or already covered by an estate).

        Giveaway alerts share estates with parser posts: if Pikabu/VGTimes already reported this giveaway,
        nothing is sent; otherwise the alert is registered as an estate so later posts join it.
        """
        if alert_type == "became_free" and game_keys.is_forever_free_info(game_info):
            # Went free-to-play for good — the channel only wants temporary giveaways and deals
            logger.info("[%s] Skipping %r — free forever", self.LOG_PREFIX, display_name)
            return True

        estate = self._estate_identity(display_name, url, store, kind_hint) if alert_type == "became_free" else None
        if estate:
            existing = await self._find_estate(estate)
            if existing:
                logger.info("[%s] Skipping %r — already covered by estate %s", self.LOG_PREFIX, display_name, existing[:8])
                return True

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
            worth=worth,
        )
        ref = await self.bot.send_message(message, images=images)
        if ref and estate:
            await self._register_estate(estate, ref, short_description, images)
        return bool(ref)

    # ── Estate integration ────────────────────────────────────────────────

    @staticmethod
    def _estate_identity(name: str, url: str, store: str, kind_hint: str = "") -> dict:
        store = "epicgames" if store == "egs" else store
        games = game_keys.games_from_links({store: [url]}) if game_keys.store_key(store, url) else []
        if games:
            games[0]["name"] = name
        else:
            games = [{"name": name, "links": {}, "info": {}}]
        return {
            "title": name,
            "games": games,
            "keys": game_keys.estate_keys(name, games),
            "kind": game_keys.event_kind(True, name, kind_hint),
        }

    async def _find_estate(self, estate: dict) -> Optional[str]:
        try:
            return await self.storage.find_matching_estate(estate["keys"], estate["title"], estate["kind"])
        except Exception as e:
            logger.debug("[%s] Estate lookup unavailable: %s", self.LOG_PREFIX, e)
            return None

    async def _register_estate(self, estate: dict, ref, description: Optional[str], images: Optional[list]) -> None:
        try:
            estate_id = uuid.uuid4().hex
            await self.storage.upsert_estate(
                estate_id, estate["title"], kind=estate["kind"], is_free=True, description=description or "",
                source=self.LOG_PREFIX, images=images or [], games=estate["games"], keys=estate["keys"],
            )
            await self.storage.mark_estate_flushed(
                estate_id, sent=True, message_id=ref.message_id, is_caption=ref.is_caption,
            )
        except Exception as e:
            logger.debug("[%s] Estate registration unavailable: %s", self.LOG_PREFIX, e)

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
            if notified_price is not None:
                # Compare by discount % to avoid re-alerting on minor UAH rate fluctuations.
                # Re-alert only when the discount changed by more than 5 percentage points.
                stored_original = stored.get("original_price_uah") or new_original
                notified_disc = round((1 - notified_price / stored_original) * 100) if stored_original > 0 else 0
                if abs(new_discount - notified_disc) < 5:
                    return None
            return "big_discount"

        return None
