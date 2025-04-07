import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

from models.models import Post, ProcessedPost

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Кастомный JSON-энкодер для обработки объектов datetime."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class PostStorage:
    def __init__(self, db_path: str = "news_bot.db"):
        self.db_path = db_path
        self.posts: Dict[str, Post] = {}
        self.processed_posts: Set[str] = set()
        self._load_data()

    def _load_data(self):
        """Загрузка данных из файла."""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Преобразуем строки дат обратно в объекты datetime
                    for post_id, post_data in data.get("posts", {}).items():
                        if "date" in post_data and post_data["date"]:
                            post_data["date"] = datetime.fromisoformat(post_data["date"])
                        if "metadata" in post_data and "date" in post_data["metadata"] and post_data["metadata"]["date"]:
                            post_data["metadata"]["date"] = datetime.fromisoformat(post_data["metadata"]["date"])
                    self.posts = {
                        post_id: Post(**post_data)
                        for post_id, post_data in data.get("posts", {}).items()
                    }
                    self.processed_posts = set(data.get("processed_posts", []))
            logger.info(f"Loaded {len(self.posts)} posts and {len(self.processed_posts)} processed posts")
        except Exception as e:
            logger.error(f"Error loading data: {str(e)}")
            self.posts = {}
            self.processed_posts = set()

    def _save_data(self):
        """Сохранение данных в файл."""
        try:
            data = {
                "posts": {
                    post_id: post.dict()
                    for post_id, post in self.posts.items()
                },
                "processed_posts": list(self.processed_posts),
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
            logger.info(f"Saved {len(self.posts)} posts and {len(self.processed_posts)} processed posts")
        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")

    def save_post(self, post: Post):
        """Сохранение поста."""
        try:
            self.posts[post.id] = post
            self._save_data()
            logger.info(f"Saved post {post.id} with title: {post.title}")
            logger.info(f"Total posts in storage: {len(self.posts)}")
        except Exception as e:
            logger.error(f"Error saving post {post.id}: {str(e)}")

    def get_post(self, post_id: str) -> Optional[Post]:
        """Получение поста по ID."""
        return self.posts.get(post_id)

    def mark_as_processed(self, post_id: str):
        """Пометка поста как обработанного."""
        try:
            self.processed_posts.add(post_id)
            # Сохраняем данные сразу после пометки поста
            self._save_data()
            logger.info(f"Marked post {post_id} as processed and saved to storage")
        except Exception as e:
            logger.error(f"Error marking post {post_id} as processed: {str(e)}")

    def is_processed(self, post_id: str) -> bool:
        """Проверка, был ли пост обработан."""
        return post_id in self.processed_posts

    def cleanup_old_posts(self, days: int = 7):
        """Очистка старых постов."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            old_post_ids = [
                post_id
                for post_id, post in self.posts.items()
                if post.created_at is not None and post.created_at < cutoff_date
            ]
            for post_id in old_post_ids:
                del self.posts[post_id]
                self.processed_posts.discard(post_id)
            self._save_data()
            logger.info(f"Cleaned up {len(old_post_ids)} old posts")
        except Exception as e:
            logger.error(f"Error cleaning up old posts: {str(e)}")

    def close(self) -> None:
        """Закрытие хранилища"""
        self._save_data() 