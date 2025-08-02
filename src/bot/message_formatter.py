"""Message formatting utilities for GamesParser bot."""

import logging
from urllib.parse import urlparse

from src.models.models import Post


logger = logging.getLogger(__name__)


class MessageFormatter:
    """Class for formatting messages and URLs for TelegramNewsBot."""

    def clean_url(self, url: str) -> str:
        """Очистка URL от реферальных параметров и валидация."""
        if not url:
            return ""
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if not parsed.scheme or not parsed.netloc:
            logger.warning("Invalid URL format: %s", url)
            return ""
        if parsed.scheme != "https":
            clean_url = clean_url.replace("http://", "https://")
        return clean_url

    def _format_store_links(self, post: Post) -> str:
        store_links = []
        for store, url in post.metadata.store_links.items():
            clean_url = self.clean_url(url)
            store_links.append(f'<a href="{clean_url}">{store}</a>')
        return " | ".join(store_links) if store_links else None

    def _format_metadata(self, post: Post) -> list:
        metadata = []
        if post.metadata and post.metadata.date:
            formatted_date = post.metadata.date.strftime("%d.%m.%Y %H:%M")
            metadata.append(f"📅 {formatted_date}")
        rating_text = f"⭐ {post.metadata.rating}" if post.metadata and post.metadata.rating else None
        if rating_text:
            metadata.append(f"📊 {rating_text}")
        return metadata

    def _linkify_urls(self, text: str) -> str:
        """Заменяет все http(s) ссылки на HTML-ссылки."""
        import re
        url_pattern = re.compile(r'(https?://[^\s]+)')
        def repl(match):
            url = match.group(0)
            return f'<a href="{url}">ссылка</a>'
        return url_pattern.sub(repl, text)

    def _remove_long_underscores(self, text: str) -> str:
        """Удаляет строки, состоящие из 10+ подчеркиваний подряд."""
        import re
        return re.sub(r'_ {0,}_+', '', text)

    def format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки."""
        try:
            title_link = f'<a href="{post.link}">{post.title}</a>'
            stores_text = self._format_store_links(post)
            metadata = self._format_metadata(post)
            text = post.content
            # Удаляем длинные подчеркивания
            text = self._remove_long_underscores(text)
            # Заменяем ссылки на HTML-ссылки
            text = self._linkify_urls(text)
            text = text[:500] + "..." if len(text) > 500 else text
            message_parts = [
                f"🎮 {title_link}",
                f"🛒 {stores_text}" if stores_text else None,
                *metadata,
                "",
                text,
            ]
            return "\n".join(filter(None, message_parts))
        except Exception as e:
            logger.error("Error formatting message: %s", str(e))
            return f"Error formatting message: {str(e)}"
