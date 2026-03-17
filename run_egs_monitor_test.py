"""Test run of EgsPriceMonitor using test DB and test Telegram channel."""

import asyncio
import logging

from src.bot.bot import TelegramNewsBot
from src.common.logger import logger
from src.config.config import settings
from src.monitors.egs_price_monitor import EgsPriceMonitor
from src.storage.sqlite_storage import SQLiteStorage


async def main():
    channel_id = settings.TEST_CHANNEL_ID
    db_path = settings.TEST_DB_PATH

    if not channel_id:
        print("TEST_CHANNEL_ID not set in .env")
        return

    logger.info("=== EGS Monitor Test Run ===")
    logger.info("DB: %s | Channel: %s", db_path, channel_id)

    storage = SQLiteStorage(db_path)
    bot = TelegramNewsBot(token=settings.TELEGRAM_BOT_TOKEN, channel_id=channel_id)

    monitor = EgsPriceMonitor(storage=storage, bot=bot)

    try:
        await storage.init_egs_tables()

        # Run a single cycle (not the infinite loop)
        await monitor._run_cycle()

        # Show what's in DB after the cycle
        conn = await storage._get_connection()
        async with conn.execute("SELECT COUNT(*) FROM egs_catalog") as cur:
            total = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT COUNT(*) FROM egs_catalog WHERE price_uah IS NOT NULL"
        ) as cur:
            with_price = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT COUNT(*) FROM egs_catalog WHERE notified_at IS NOT NULL"
        ) as cur:
            notified = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT url_slug, name, price_uah, original_price_uah, discount_pct "
            "FROM egs_catalog WHERE notified_at IS NOT NULL LIMIT 10"
        ) as cur:
            alerted = await cur.fetchall()

        logger.info("=== Results ===")
        logger.info("Total games in DB: %d", total)
        logger.info("Games with price:  %d", with_price)
        logger.info("Alerts sent:       %d", notified)
        if alerted:
            logger.info("Sample alerts:")
            for row in alerted:
                slug, name, price, orig, disc = row
                logger.info(
                    "  %r ₴%s -> ₴%s (-%d%%)",
                    name,
                    f"{orig // 100}" if orig else "?",
                    f"{price // 100}" if price is not None else "?",
                    disc or 0,
                )

    finally:
        await storage.close()
        await bot.close()
        monitor.catalog_service.close()


if __name__ == "__main__":
    root_handler = logging.StreamHandler(
        open(logging.StreamHandler().stream.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    )
    root_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.root.addHandler(root_handler)
    logging.root.setLevel(logging.INFO)
    asyncio.run(main())
