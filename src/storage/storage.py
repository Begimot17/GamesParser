import json
import logging
import os
from typing import Set

logger = logging.getLogger(__name__)


class PostStorage:
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self.processed_posts: Set[str] = set()
        self._load_data()

    def _load_data(self):
        """Загрузка данных из файла."""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_posts = set(data.get("processed_posts", []))
            logger.info(f"Loaded {len(self.processed_posts)} processed posts")
        except Exception as e:
            logger.error(f"Error loading data: {str(e)}")
            self.processed_posts = set()

    def _save_data(self):
        """Сохранение данных в файл."""
        try:
            data = {
                "processed_posts": list(self.processed_posts),
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self.processed_posts)} processed posts")
        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")

    def mark_as_processed(self, post_id: str):
        """Пометка поста как обработанного."""
        try:
            self.processed_posts.add(post_id)
            self._save_data()
            logger.info(f"Marked post {post_id} as processed")
        except Exception as e:
            logger.error(f"Error marking post {post_id} as processed: {str(e)}")

    def is_processed(self, post_id: str) -> bool:
        """Проверка, был ли пост обработан."""
        return post_id in self.processed_posts

    def close(self) -> None:
        """Закрытие хранилища"""
        self._save_data()

    def cleanup_old_posts(self) -> None:
        """Очистка старых постов из памяти."""
        try:
            old_count = len(self.processed_posts)
            self.processed_posts.clear()
            self._save_data()
            logger.info(f"Cleaned up {old_count} old posts from memory")
        except Exception as e:
            logger.error(f"Error cleaning up old posts: {str(e)}") 