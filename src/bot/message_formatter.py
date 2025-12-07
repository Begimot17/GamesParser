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
        # Ensure url is a string before parsing
        url_str = str(url) if not isinstance(url, str) else url
        if not url_str:
            return ""
        parsed = urlparse(url_str)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if not parsed.scheme or not parsed.netloc:
            logger.warning("Invalid URL format: %s", url_str)
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
        # Removed: text = re.sub(r"_+", "", text) # This might be causing issues with Telegram's HTML parsing

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
        # Ensure text is a string before escaping
        text_str = str(text) if not isinstance(text, str) else text
        return html.escape(text_str)

    def to_plain_text(self, html_text: str) -> str:
        """Converts HTML text to plain text by removing tags and unescaping entities."""
        # Remove HTML tags
        clean = re.compile('<.*?>')
        plain_text = re.sub(clean, '', html_text)
        # Unescape HTML entities
        return html.unescape(plain_text)

    def format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Форматирует дату в строку."""
        return dt.strftime("%d.%m.%Y %H:%M") if dt else None

    def _format_store_links(self, post: Post) -> str:
        store_links = []
        if post.metadata and post.metadata.store_links:
            for store, url in post.metadata.store_links.items():
                # Ensure url is a string before passing to clean_url
                clean_url = self.clean_url(str(url))
                # Escape the store name before putting it into the link text
                store_links.append(f'<a href="{self.escape_html(clean_url)}">{self.escape_html(store)}</a>')
        return " | ".join(store_links) if store_links else ""

    def format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки."""
        try:
            # Header: Title linked
            title_link = f'<a href="{self.escape_html(str(post.link))}">{self.escape_html(post.title)}</a>'
            
            # Content: Truncated
            cleaned_content = self.clean_text(post.content, final_clean=True)
            escaped_content = self.escape_html(cleaned_content)
            # Limit content length to avoid hitting Telegram limits (4096 chars total, keep safe buffer)
            max_content_len = 800 
            content_display = escaped_content[:max_content_len] + "..." if len(escaped_content) > max_content_len else escaped_content

            # Meta Line: Date | Rating | Views
            meta_parts = []
            if post.metadata:
                if post.metadata.date:
                    meta_parts.append(f"📅 {self.format_date(post.metadata.date)}")
                if post.metadata.rating is not None:
                    meta_parts.append(f"⭐ {post.metadata.rating}")
                if hasattr(post.metadata, 'views') and post.metadata.views:
                     meta_parts.append(f"👁 {post.metadata.views}")

            meta_line = " | ".join(meta_parts) if meta_parts else ""

            # Store Links
            stores_line = self._format_store_links(post)
            if stores_line:
                stores_line = f"🛒 {stores_line}"

            # Tags (Hashtags)
            tags_line = ""
            if hasattr(post.metadata, 'tags') and post.metadata.tags:
                 # Clean tags to be valid hashtags (no spaces, alphanumeric)
                 clean_tags = [re.sub(r"[^\w]", "", t) for t in post.metadata.tags]
                 tags_line = " ".join([f"#{t}" for t in clean_tags if t])

            # Assemble Message
            message_parts = [
                f"<b>{title_link}</b>",
                "",
                content_display,
                "",
                meta_line,
                stores_line,
                tags_line
            ]
            
            return "\n".join(filter(None, message_parts))

        except Exception as e:
            logger.error("Error formatting message: %s", str(e), exc_info=True)
            return f"Error formatting message: {post.link}"
