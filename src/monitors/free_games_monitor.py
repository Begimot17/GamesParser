"""Monitor for permanently free games on GOG, IndieGala, GamerPower, and more."""

from src.common.logger import logger
from src.monitors.base_price_monitor import PriceMonitorBase


class FreeGamesMonitor(PriceMonitorBase):
    """Scans free-game services and sends one-time alerts per game."""

    LOG_PREFIX = "FreeGames"

    def __init__(self, storage, bot, scan_interval=None, services=None):
        super().__init__(storage, bot, scan_interval)
        self.services = services or []

    async def _init_store_tables(self) -> None:
        await self.storage.init_free_games_tables()

    async def _run_cycle(self) -> None:
        total_new = 0
        for service in self.services:
            try:
                games = await service.fetch_free_games()
            except Exception as e:
                logger.warning("[FreeGames] %s fetch failed: %s", service.PLATFORM, e)
                continue

            logger.info("[FreeGames] %s: %d games returned", service.PLATFORM, len(games))

            for game in games:
                # Some services (GamerPower) carry per-item platform override
                platform = game.get("platform") or service.PLATFORM
                gid = f"{service.PLATFORM}:{game['id']}"
                stored = await self.storage.get_free_game(gid)
                if stored and stored.get("notified_at"):
                    continue  # already notified

                # _dispatch_alert skips giveaways already covered by an estate (parser posts)
                success = await self._dispatch_alert(
                    display_name=game["name"],
                    url=game["url"],
                    stored={},
                    new_price=0,
                    new_original=None,
                    new_discount=100,
                    alert_type="became_free",
                    game_info=None,
                    images=[game["image_url"]] if game.get("image_url") else None,
                    short_description=game.get("description"),
                    cross_store_data=None,
                    store=platform,
                    worth=game.get("worth"),
                    kind_hint=game.get("platforms", ""),
                )
                await self.storage.upsert_free_game(gid, platform, game, success)
                if success:
                    total_new += 1
                    logger.info("[FreeGames] Alert sent: %s (%s)", game["name"], platform)

        logger.info("[FreeGames] Cycle complete. New alerts sent: %d", total_new)
