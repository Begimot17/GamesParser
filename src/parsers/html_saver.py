"""HTML saver utility for GamesParser project."""

from pathlib import Path

import aiofiles

from src.common import logger
from src.config.config import Config


class HTMLSaver:
    """Класс для сохранения HTML статей."""

    def __init__(self):
        """Инициализация HTMLSaver."""
        if Config.SAVE_HTML and not Path(Config.HTML_DIR).exists():
            Path(Config.HTML_DIR).mkdir(parents=True)

    async def save_article_html(self, html_content: str, post_id: str) -> None:
        """Сохраняет HTML статьи в файл."""
        try:
            filename = f"{post_id}.html"
            filepath = Path(Config.HTML_DIR) / filename
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(html_content)
            logger.info(f"Saved HTML for post {post_id} to {filepath}")
        except Exception as e:
            logger.error(f"Error saving HTML for post {post_id}: {e}")
