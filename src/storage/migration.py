import asyncio
import json
from datetime import datetime

import aiosqlite

from src.common.logger import logger
from src.config.config import settings


async def migrate_json_to_sqlite():
    """Migrates processed posts from JSON file to SQLite database."""
    json_path = settings.BASE_DIR / "processed_posts.json"
    if not json_path.exists():
        logger.info("No processed_posts.json found. Skipping migration.")
        return

    logger.info(f"Found processed_posts.json at {json_path}. Starting migration...")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.warning("processed_posts.json content is not a list. Skipping.")
            return

        processed_ids = set(data)
        count = 0

        async with aiosqlite.connect(settings.DB_PATH) as db:
            # Ensure table exists (in case storage hasn't run yet)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS processed_posts (id TEXT PRIMARY KEY, processed_at TIMESTAMP)",
            )
            await db.commit()

            for post_id in processed_ids:
                try:
                    await db.execute(
                        "INSERT OR IGNORE INTO processed_posts (id, processed_at) VALUES (?, ?)",
                        (str(post_id), datetime.now()),
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"Error migrating post {post_id}: {e}")

            await db.commit()

        logger.info(f"Migration completed. Migrated {count} posts from JSON to SQLite.")

        # Rename old file to avoid re-migration or confusion
        # backup_path = json_path.with_suffix(".json.bak")
        # json_path.rename(backup_path)
        # logger.info(f"Renamed processed_posts.json to {backup_path.name}")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(migrate_json_to_sqlite())
