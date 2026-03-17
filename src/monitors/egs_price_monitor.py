"""EGS price monitor: scans on-sale EGS catalog and notifies on price changes."""

import asyncio
from datetime import datetime
from typing import Optional

from src.bot.bot import TelegramNewsBot
from src.bot.message_formatter import MessageFormatter
from src.common.logger import logger
from src.config.config import settings
from src.services.egs_catalog_service import EgsCatalogService
from src.services.price_service import GameInfo
from src.storage.sqlite_storage import SQLiteStorage


class EgsPriceMonitor:
    """Periodically scans on-sale EGS games and sends alerts on significant price changes.

    Uses Epic GraphQL API as the data source.
    Prices are stored and compared in UAH kopecks.
    """

    def __init__(self, storage: SQLiteStorage, bot: TelegramNewsBot):
        self.storage = storage
        self.bot = bot
        self.formatter = MessageFormatter()
        self.catalog_service = EgsCatalogService()
        self._scan_interval = settings.EGS_SCAN_INTERVAL
        self._discount_threshold = settings.EGS_DISCOUNT_THRESHOLD

    async def run(self) -> None:
        """Main loop: run a scan cycle, then sleep for EGS_SCAN_INTERVAL seconds."""
        logger.info("[EGSMonitor] Starting EGS price monitor (interval=%ds)", self._scan_interval)
        await self.storage.init_egs_tables()
        while True:
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error("[EGSMonitor] Cycle error: %s", e, exc_info=True)
            logger.info("[EGSMonitor] Sleeping for %d seconds until next scan", self._scan_interval)
            await asyncio.sleep(self._scan_interval)

    async def _run_cycle(self) -> None:
        """Single scan cycle: fetch all on-sale prices from EGS, detect changes, send alerts."""
        logger.info("[EGSMonitor] Starting scan cycle at %s", datetime.now().isoformat())

        pending: list[dict] = []

        def on_result(slug: str, data: dict) -> None:
            pending.append({"slug": slug, "data": data})

        total = await self.catalog_service.scan_all_prices(on_result)
        logger.info("[EGSMonitor] Scanned %d games. Processing...", total)

        alert_count = 0
        update_batch: list[dict] = []

        for item in pending:
            slug = item["slug"]
            data = item["data"]
            name = data.get("name", "")

            price_data = {
                "price_uah": data["price_uah"],
                "original_price_uah": data["original_price_uah"],
                "discount_pct": data["discount_pct"],
            }

            alert_sent = await self._process_result(
                slug, name, data["url"], price_data,
                key_image=data.get("key_image"),
                description=data.get("description"),
                developer=data.get("developer", ""),
                genre=data.get("genre", ""),
                has_controller_support=data.get("has_controller_support", False),
                has_multiplayer=data.get("has_multiplayer", False),
            )
            if alert_sent:
                alert_count += 1

            update_batch.append({
                "url_slug": slug,
                "name": name or None,
                "url": data["url"],
                "price_uah": price_data["price_uah"],
                "original_price_uah": price_data["original_price_uah"],
                "discount_pct": price_data["discount_pct"],
                "key_image": data.get("key_image"),
                "description": data.get("description"),
                "last_checked": datetime.now().isoformat(),
            })

            if len(update_batch) >= 500:
                await self.storage.upsert_egs_games(update_batch)
                update_batch.clear()

        if update_batch:
            await self.storage.upsert_egs_games(update_batch)

        logger.info("[EGSMonitor] Cycle done. Games: %d, Alerts: %d", total, alert_count)

    async def _process_result(
        self,
        slug: str,
        name: str,
        url: str,
        price_data: dict,
        key_image: Optional[str] = None,
        description: Optional[str] = None,
        developer: str = "",
        genre: str = "",
        has_controller_support: bool = False,
        has_multiplayer: bool = False,
    ) -> bool:
        """Check if a price change warrants an alert. Returns True if alert was sent."""
        stored = await self.storage.get_egs_game(slug)

        # First time we see this game — just store, never alert
        if stored is None or stored.get("price_uah") is None:
            return False

        new_price = price_data["price_uah"]
        new_original = price_data["original_price_uah"]
        new_discount = price_data["discount_pct"]

        alert_type = self._detect_change(stored, new_price, new_original, new_discount)
        if not alert_type:
            return False

        display_name = name or (stored or {}).get("name") or slug

        # Cross-store enrichment: check if Steam had a recent alert for this game
        cross_store_data = None
        if display_name:
            try:
                steam_row = await self.storage.find_steam_game_by_name(display_name)
                if steam_row and steam_row.get("notified_at"):
                    try:
                        notified_dt = datetime.fromisoformat(steam_row["notified_at"])
                    except (ValueError, TypeError):
                        notified_dt = None
                    if notified_dt:
                        age = (datetime.now() - notified_dt).total_seconds()
                        if age < 1800:
                            cross_store_data = {
                                "store": "steam",
                                "url": steam_row.get("url", ""),
                                "price_uah": steam_row.get("price_uah"),
                                "original_price_uah": steam_row.get("original_price_uah"),
                                "discount_pct": steam_row.get("discount_pct"),
                            }
            except Exception as e:
                logger.debug("[EGSMonitor] Cross-store lookup failed for %r: %s", display_name, e)

        # Use stored key_image/description if not available in current data
        img = key_image or (stored or {}).get("key_image")
        desc = description or (stored or {}).get("description")

        # Build GameInfo from EGS scan data (genre, developer, features)
        game_info = GameInfo(
            genre=genre or None,
            developer=developer or None,
            has_controller_support=has_controller_support,
            has_multiplayer=has_multiplayer,
            short_description=desc,
        ) if (genre or developer or has_controller_support or has_multiplayer) else None

        message = self.formatter.format_price_alert(
            name=display_name,
            url=url,
            old_price_uah=stored.get("price_uah"),
            new_price_uah=new_price,
            original_price_uah=new_original,
            discount_pct=new_discount,
            alert_type=alert_type,
            game_info=game_info,
            store="egs",
            cross_store_data=cross_store_data,
            short_description=desc,
        )

        images = [img] if img else None
        success = await self.bot.send_message(message, images=images)
        if success:
            await self.storage.update_egs_notification(slug, new_price)
            logger.info(
                "[EGSMonitor] Alert sent slug=%s %r type=%s price=%s->%d",
                slug, display_name, alert_type, stored.get("price_uah"), new_price,
            )
        return success

    def _detect_change(
        self,
        stored: dict,
        new_price: int,
        new_original: Optional[int],
        new_discount: int,
    ) -> Optional[str]:
        """Return alert type or None.

        Rules:
        - Alert only when the price CHANGED compared to the stored price.
        - 'became_free'  : had a positive original price, now 0, price is different from stored
        - 'big_discount' : discount_pct >= threshold and price is different from stored
        - Never re-alert at the same price that was already notified.
        """
        if new_original is None:
            return None

        stored_price = stored.get("price_uah")
        notified_price = stored.get("notified_price_uah")

        # Price hasn't changed since last scan — nothing to report
        if stored_price is not None and stored_price == new_price:
            return None

        # Price changed — check if it qualifies for an alert
        if new_original > 0 and new_price == 0:
            if notified_price != new_price:
                return "became_free"
            return None

        if new_discount >= self._discount_threshold and new_original > 0:
            if notified_price != new_price:
                return "big_discount"
            return None

        return None
