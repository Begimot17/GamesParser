"""Database storage for GamesParser project."""

import json
from pathlib import Path

from common import logger
from src.config.config import Config
from src.storage.storage import BaseStorage


class Database(BaseStorage):
    """Класс для работы с базой данных обработанных постов."""

    def __init__(self, db_path: str = "news_bot.db"):
        super().__init__(db_path)
        self.db_path = db_path
        self.processed_posts = set()
        # Удаляю метод _load_data, чтобы использовать только из BaseStorage

    def _save_data(self):
        """Сохранение данных в файл."""
        try:
            data = {
                "processed_posts": list(self.processed_posts),
            }
            with Path(self.db_path).open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self.processed_posts)} processed posts")
        except (OSError, TypeError) as e:
            logger.error(f"Error saving data: {str(e)}", exc_info=True)

    def mark_as_processed(self, post_id: str):
        """Пометка поста как обработанного."""
        try:
            self.processed_posts.add(post_id)
            self._save_data()
            logger.info(f"Marked post {post_id} as processed")
        except Exception as e:
            logger.error(f"Error marking post {post_id} as processed: {str(e)}", exc_info=True)

    def is_processed(self, post_id: str) -> bool:
        """Проверка, был ли пост обработан."""
        return post_id in self.processed_posts

    def close(self) -> None:
        """Закрытие базы данных."""
        self._save_data()


# Global database instance
db = Database(db_path=Config.DB_PATH)
