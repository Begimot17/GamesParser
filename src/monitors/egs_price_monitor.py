"""EGS price monitor: scans on-sale EGS catalog and notifies on price changes."""

from datetime import datetime
from typing import ClassVar, Optional

from src.bot.bot import TelegramNewsBot
from src.common.logger import logger
from src.config.config import settings
from src.monitors.base_price_monitor import PriceMonitorBase
from src.services.egs_catalog_service import EgsCatalogService
from src.services.price_service import GameInfo
from src.storage.sqlite_storage import SQLiteStorage


class EgsPriceMonitor(PriceMonitorBase):
    """Periodically scans on-sale EGS games and sends alerts on significant price changes.

    Uses Epic GraphQL API as the data source.
    Prices are stored and compared in UAH kopecks.
    """

    LOG_PREFIX: ClassVar[str] = "EGSMonitor"

    def __init__(self, storage: SQLiteStorage, bot: TelegramNewsBot, scan_interval: Optional[int] = None):
        super().__init__(storage, bot, scan_interval=scan_interval)
        self.catalog_service = EgsCatalogService()
        self._discount_threshold = settings.EGS_DISCOUNT_THRESHOLD

    async def _init_store_tables(self) -> None:
        await self.storage.init_egs_tables()

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

        if stored is None or stored.get("price_uah") is None:
            return False

        new_price = price_data["price_uah"]
        new_original = price_data["original_price_uah"]
        new_discount = price_data["discount_pct"]

        alert_type = self._detect_change(stored, new_price, new_original, new_discount, self._discount_threshold)
        if not alert_type:
            return False

        display_name = name or (stored or {}).get("name") or slug

        # Cross-store: check if Steam had a recent alert for this game
        cross_store_data = None
        if display_name:
            try:
                steam_row = await self.storage.find_steam_game_by_name(display_name)
                cross_store_data = self._extract_cross_store_row(steam_row, "steam")
            except Exception as e:
                logger.debug("[EGSMonitor] Cross-store lookup failed for %r: %s", display_name, e)

        img = key_image or (stored or {}).get("key_image")
        desc = description or (stored or {}).get("description")

        game_info = GameInfo(
            genre=genre or None,
            developer=developer or None,
            has_controller_support=has_controller_support,
            has_multiplayer=has_multiplayer,
            short_description=desc,
        ) if (genre or developer or has_controller_support or has_multiplayer) else None

        success = await self._dispatch_alert(
            display_name, url, stored or {},
            new_price, new_original, new_discount,
            alert_type, game_info,
            [img] if img else None, desc, cross_store_data, "egs",
        )
        if success:
            await self.storage.update_egs_notification(slug, new_price)
            logger.info(
                "[EGSMonitor] Alert sent slug=%s %r type=%s price=%s->%d",
                slug, display_name, alert_type, stored.get("price_uah"), new_price,
            )
        return success
