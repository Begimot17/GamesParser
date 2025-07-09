"""Storage for processed posts in GamesParser project."""

import json
from pathlib import Path

from common import logger


class BaseStorage:
    """Класс для хранения обработанных постов."""

    def __init__(self, db_path: str = "news_bot.db"):
        """Инициализация PostStorage."""
        self.db_path = db_path
        self.processed_posts = set()
        self._load_data()

    def _load_data(self) -> None:
        """Загрузка данных из файла."""
        if Path(self.db_path).exists():
            try:
                with Path(self.db_path).open(encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_posts = set(data.get("processed_posts", []))
                logger.info("Loaded %d processed posts", len(self.processed_posts))
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Error loading data: %s", str(e), exc_info=True)
                self.processed_posts = set()

    def _save_data(self) -> None:
        """Сохранение данных в файл."""
        try:
            data = {"processed_posts": list(self.processed_posts)}
            with Path(self.db_path).open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Saved %d processed posts", len(self.processed_posts))
        except (OSError, TypeError) as e:
            logger.error("Error saving data: %s", str(e), exc_info=True)

    def mark_as_processed(self, post_id: str) -> None:
        """Пометка поста как обработанного."""
        self.processed_posts.add(post_id)
        self._save_data()
        logger.info("Marked post %s as processed", post_id)

    def is_processed(self, post_id: str) -> bool:
        """Проверка, был ли пост обработан."""
        return post_id in self.processed_posts

    def close(self) -> None:
        """Закрытие хранилища (сохраняет данные)."""
        self._save_data()


class PostStorage(BaseStorage):
    """Класс для хранения обработанных постов."""
