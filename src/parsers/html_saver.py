"""HTML saver utility for GamesParser project."""

from pathlib import Path

import aiofiles

from src.common.logger import logger
from src.config.config import settings


class HTMLSaver:
    """Класс для сохранения HTML статей."""

    def __init__(self):
        """Инициализация HTMLSaver."""
        if settings.SAVE_HTML and not Path(settings.HTML_DIR).exists():
            Path(settings.HTML_DIR).mkdir(parents=True)

    async def save_article_html(self, html_content: str, post_id: str) -> None:
        """Сохраняет HTML статьи в файл."""
        try:
            filename = f"{post_id}.html"
            filepath = Path(settings.HTML_DIR) / filename
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(html_content)
            logger.info("Saved HTML for post %s to %s", post_id, filepath)
        except Exception as e:
            logger.error("Error saving HTML for post %s: %s", post_id, e)
