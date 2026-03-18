"""Steam price monitor: scans the full Steam catalog and notifies on price changes."""

from datetime import datetime
from typing import Optional

from src.bot.bot import TelegramNewsBot
from src.common.logger import logger
from src.config.config import settings
from src.monitors.base_price_monitor import PriceMonitorBase
from src.services.price_service import PriceService
from src.services.steam_catalog_service import SteamCatalogService
from src.storage.sqlite_storage import SQLiteStorage


class SteamPriceMonitor(PriceMonitorBase):
    """Periodically scans the full Steam catalog and sends alerts on significant price changes.

    Uses SteamSpy as the data source (no auth required).
    Prices are stored and compared in USD cents.
    """

    LOG_PREFIX = "SteamMonitor"

    def __init__(
        self,
        storage: SQLiteStorage,
        bot: TelegramNewsBot,
        scan_interval: Optional[int] = None,
        specials_only: bool = True,
    ):
        super().__init__(storage, bot, scan_interval=scan_interval)
        self.catalog_service = SteamCatalogService(specials_only=specials_only)
        self.price_service = PriceService()
        self._discount_threshold = settings.STEAM_DISCOUNT_THRESHOLD
        self._min_discount_threshold = settings.STEAM_MIN_DISCOUNT_THRESHOLD

    async def _init_store_tables(self) -> None:
        await self.storage.init_steam_tables()

    async def _run_cycle(self) -> None:
        """Single scan cycle: fetch all prices from SteamSpy, detect changes, send alerts."""
        logger.info("[SteamMonitor] Starting scan cycle at %s", datetime.now().isoformat())

        pending: list[dict] = []

        def on_result(appid: int, data: dict) -> None:
            pending.append({"appid": appid, "data": data})

        total = await self.catalog_service.scan_all_prices(on_result)
        logger.info("[SteamMonitor] Scanned %d games. Processing...", total)

        alert_count = 0
        update_batch: list[dict] = []

        for item in pending:
            appid = item["appid"]
            data = item["data"]
            name = data.get("name", "")

            price_data = {
                "price_uah": data["price_uah"],
                "original_price_uah": data["original_price_uah"],
                "discount_pct": data["discount_pct"],
            }

            alert_sent = await self._process_result(appid, name, price_data)
            if alert_sent:
                alert_count += 1

            update_batch.append({
                "appid": appid,
                "name": name or None,
                "url": f"https://store.steampowered.com/app/{appid}/",
                "price_uah": price_data["price_uah"],
                "original_price_uah": price_data["original_price_uah"],
                "discount_pct": price_data["discount_pct"],
                "last_checked": datetime.now().isoformat(),
            })

            if len(update_batch) >= 500:
                await self.storage.upsert_steam_games(update_batch)
                update_batch.clear()

        if update_batch:
            await self.storage.upsert_steam_games(update_batch)

        logger.info("[SteamMonitor] Cycle done. Games: %d, Alerts: %d", total, alert_count)

    async def _process_result(self, appid: int, name: str, price_data: dict) -> bool:
        """Check if a price change warrants an alert. Returns True if alert was sent."""
        stored = await self.storage.get_steam_game(appid)

        # First time we see this game OR first time we have price data — just store, never alert
        if stored is None or stored.get("price_uah") is None:
            return False

        new_price = price_data["price_uah"]
        new_original = price_data["original_price_uah"]
        new_discount = price_data["discount_pct"]

        alert_type = self._detect_change(stored, new_price, new_original, new_discount, self._min_discount_threshold)
        if not alert_type:
            return False

        url = f"https://store.steampowered.com/app/{appid}/"
        display_name = name or (stored or {}).get("name") or str(appid)

        try:
            game_info = await self.price_service.get_steam_info(url)
        except Exception as e:
            logger.debug("[SteamMonitor] Could not enrich game info for %d: %s", appid, e)
            game_info = None

        # Quality gate: apply dynamic threshold for big_discount alerts (became_free always passes)
        if alert_type == "big_discount":
            threshold = self._quality_adjusted_threshold(game_info)
            if threshold is None or new_discount < threshold:
                logger.debug(
                    "[SteamMonitor] Suppressed appid=%d discount=%d%% score=%d threshold=%s",
                    appid, new_discount, self._compute_quality_score(game_info), threshold,
                )
                return False

        # Cross-store enrichment: check if EGS had a recent alert for this game
        cross_store_data = None
        if display_name:
            try:
                egs_row = await self.storage.find_egs_game_by_name(display_name)
                cross_store_data = self._extract_cross_store_row(egs_row, "egs")
            except Exception as e:
                logger.debug("[SteamMonitor] Cross-store lookup failed for %r: %s", display_name, e)

        # Get header image: from game_info or fallback to CDN URL
        header_image = (
            (game_info.header_image if game_info else None)
            or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
        )
        short_description = game_info.short_description if game_info else None

        success = await self._dispatch_alert(
            display_name, url, stored or {},
            new_price, new_original, new_discount,
            alert_type, game_info,
            [header_image], short_description, cross_store_data, "steam",
        )
        if success:
            await self.storage.update_steam_notification(appid, new_price)
            logger.info(
                "[SteamMonitor] Alert sent appid=%d %r type=%s price=%s->%d",
                appid, display_name, alert_type, stored.get("price_uah"), new_price,
            )
        return success

    @staticmethod
    def _compute_quality_score(game_info) -> int:
        """Return quality score 0–100 based on review_score, recommendations_total, metacritic."""
        if game_info is None:
            return 15  # fallback: unknown game → score < 40 → suppressed

        score = 0

        # review_score: up to 50 points
        review_map = {
            "overwhelmingly positive": 50,
            "very positive": 40,
            "mostly positive": 25,
            "positive": 20,
            "mixed": 5,
        }
        rs = (game_info.review_score or "").lower()
        score += review_map.get(rs, 0)  # negatives and unknowns → 0

        # recommendations_total: up to 30 points
        recs = game_info.recommendations_total or 0
        if recs >= 100_000:
            score += 30
        elif recs >= 50_000:
            score += 25
        elif recs >= 10_000:
            score += 20
        elif recs >= 1_000:
            score += 12
        elif recs >= 100:
            score += 5

        # metacritic: up to 20 points
        mc = game_info.metacritic or 0
        if mc >= 85:
            score += 20
        elif mc >= 75:
            score += 15
        elif mc >= 65:
            score += 10
        elif mc >= 50:
            score += 5

        return score

    def _quality_adjusted_threshold(self, game_info) -> Optional[int]:
        """Return minimum discount % required for an alert, or None to suppress entirely.

        Score tiers (max 100):
          >= 80 — top quality (overwhelmingly/very positive + large audience): 65%+
          >= 60 — good quality: 75%+
          >= 40 — decent quality: 85%+
          <  40 — unknown / low quality / no data: suppress
        """
        score = self._compute_quality_score(game_info)
        if score >= 80:
            return 65   # was 50
        if score >= 60:
            return 75   # was 65
        if score >= 40:
            return 85   # was 75
        return None     # score < 40 → suppress (was: 20-39 @ 85%, 10-19 @ 90%)

