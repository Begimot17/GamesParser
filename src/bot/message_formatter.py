"""Message formatting utilities for GamesParser bot."""

import html
import logging
import re
from datetime import datetime
from typing import Optional
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

    def clean_text(self, text: str, final_clean: bool = False) -> str:
        """Очистка текста от лишних символов, пробелов и ссылок."""
        if not text:
            return ""

        text = text.strip()
        text = re.sub(r"https?://(?:store\.)?steampowered\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?epicgames\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?gog\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?itch\.io/\S+", "", text)
        text = re.sub(r"_+", "", text)

        if final_clean:
            lines = [line.strip() for line in text.splitlines()]
            cleaned_lines = []
            prev_empty = False
            for line in lines:
                if line == "":
                    if not prev_empty:
                        cleaned_lines.append("")
                    prev_empty = True
                else:
                    cleaned_lines.append(line)
                    prev_empty = False
            return "\n".join(cleaned_lines).strip()
        else:
            text = re.sub(r"\s+", " ", text)
            text = re.sub(r"\n+", " ", text)
            return text

    def escape_html(self, text: str) -> str:
        """Экранирует специальные HTML-символы."""
        return html.escape(text)

    def format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Форматирует дату в строку."""
        return dt.strftime("%d.%m.%Y %H:%M") if dt else None

    def _format_store_links(self, post: Post) -> str:
        store_links = []
        if post.metadata and post.metadata.store_links:
            for store, url in post.metadata.store_links.items():
                clean_url = self.clean_url(url)
                store_links.append(f'<a href="{clean_url}">{store}</a>')
        return " | ".join(store_links) if store_links else ""

    def format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки."""
        try:
            title_link = f'<a href="{post.link}">{self.escape_html(post.title)}</a>'
            stores_text = self._format_store_links(post)

            metadata_parts = []
            if post.metadata and post.metadata.date:
                metadata_parts.append(f"📅 {self.format_date(post.metadata.date)}")
            if post.metadata and post.metadata.rating is not None:
                metadata_parts.append(f"⭐ {post.metadata.rating}")

            content = self.clean_text(post.content, final_clean=True)
            content = content[:500] + "..." if len(content) > 500 else content

            message_parts = [
                f"🎮 {title_link}",
                f"🛒 {stores_text}" if stores_text else None,
                " | ".join(metadata_parts) if metadata_parts else None,
                "",
                content,
            ]
            return "\n".join(filter(None, message_parts))
        except Exception as e:
            logger.error("Error formatting message: %s", str(e), exc_info=True)
            return f"Error formatting message: {post.link}"
