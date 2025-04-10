import logging
import os

import aiofiles

from src.config.config import Config

logger = logging.getLogger(__name__)


class HTMLSaver:
    def __init__(self):
        if Config.SAVE_HTML and not os.path.exists(Config.HTML_DIR):
            os.makedirs(Config.HTML_DIR)

    async def save_article_html(self, html_content: str, post_id: str) -> None:
        """Сохранение HTML-контента статьи в файл"""
        if not Config.SAVE_HTML:
            return

        try:
            filename = f"{post_id}.html"
            filepath = os.path.join(Config.HTML_DIR, filename)

            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(html_content)

            logger.info("Saved HTML for post %s to %s", post_id, filename)
        except Exception as e:
            logger.error("Error saving HTML for post %s: %s", post_id, str(e))
