"""Storage for processed posts in GamesParser project."""

import json
from pathlib import Path

from src.common.logger import logger
from src.storage.base import Storage


class JsonStorage(Storage):
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self.processed_posts = set()
        self._load_data()

    def _load_data(self) -> None:
        if Path(self.db_path).exists():
            try:
                with Path(self.db_path).open(encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_posts = set(data.get("processed_posts", []))
                logger.info(f"Loaded {len(self.processed_posts)} processed posts")
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Error loading data: {e}", exc_info=True)
                self.processed_posts = set()

    def _save_data(self) -> None:
        try:
            data = {"processed_posts": list(self.processed_posts)}
            with Path(self.db_path).open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self.processed_posts)} processed posts")
        except (OSError, TypeError) as e:
            logger.error(f"Error saving data: {e}", exc_info=True)

    def mark_as_processed(self, post_id: str) -> None:
        self.processed_posts.add(post_id)
        self._save_data()
        logger.info(f"Marked post {post_id} as processed")

    def is_processed(self, post_id: str) -> bool:
        return post_id in self.processed_posts

    def close(self) -> None:
        self._save_data()
