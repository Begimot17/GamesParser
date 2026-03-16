"""Message formatting utilities for GamesParser bot."""

import html
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from src.models.models import Post
from src.services.price_service import GameInfo


logger = logging.getLogger(__name__)

STORE_EMOJIS = {
    "steam": "🎮",
    "epicgames": "🟣",
    "gog": "🔵",
    "itch": "🎲",
}

STORE_DISPLAY_NAMES = {
    "steam": "Steam",
    "epicgames": "Epic Games",
    "gog": "GOG",
    "itch": "itch.io",
}


class MessageFormatter:
    """Class for formatting messages and URLs for TelegramNewsBot."""

    def clean_url(self, url: str) -> str:
        """Очистка URL от реферальных параметров и валидация."""
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
        text_str = str(text) if not isinstance(text, str) else text
        return html.escape(text_str)

    def to_plain_text(self, html_text: str) -> str:
        """Converts HTML text to plain text by removing tags and unescaping entities."""
        plain_text = re.sub(re.compile("<.*?>"), "", html_text)
        return html.unescape(plain_text)

    def format_date(self, dt: Optional[datetime]) -> Optional[str]:
        """Форматирует дату в строку."""
        return dt.strftime("%d.%m.%Y %H:%M") if dt else None

    def _truncate_content(self, text: str, max_len: int = 600) -> str:
        """Умная обрезка: по последней границе предложения в диапазоне [max_len-200, max_len]."""
        if len(text) <= max_len:
            return text
        snippet = text[:max_len]
        for sep in (".", "!", "?", "\n"):
            idx = snippet.rfind(sep, max_len - 200)
            if idx > 0:
                return snippet[:idx + 1] + "…"
        return snippet + "…"

    # ── Game info helpers ─────────────────────────────────────────────────

    def _game_name_from_url(self, url: str) -> Optional[str]:
        """Extract a human-readable game name from a store URL slug."""
        try:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            if not path:
                return None
            segment = [p for p in path.split("/") if p][-1]
            name = segment.replace("-", " ").replace("_", " ").title()
            return name if name else None
        except Exception:
            return None

    def _load_game_info(self, raw: Optional[dict]) -> Optional[GameInfo]:
        """Restore GameInfo from a stored dict (or None)."""
        if not raw or not isinstance(raw, dict):
            return None
        return GameInfo.from_dict(raw)

    def _format_game_info_line(self, info: Optional[GameInfo]) -> str:
        """Return a compact summary string for one GameInfo (price + genre + mc + dev)."""
        if not info:
            return ""
        parts = []
        price_str = info.format_price()
        if price_str:
            parts.append(price_str)
        if info.genre:
            parts.append(f"🎭 {self.escape_html(info.genre)}")
        if info.metacritic is not None:
            parts.append(f"📊 Metacritic: {info.metacritic}")
        if info.review_score:
            parts.append(f"💬 {self.escape_html(info.review_score)}")
        if info.developer:
            parts.append(f"👾 {self.escape_html(info.developer)}")
        return " | ".join(parts)

    def _format_one_store_entry(self, store: str, url: str, info: Optional[GameInfo], label: str) -> str:
        """Format one store entry line."""
        emoji = STORE_EMOJIS.get(store.lower(), "🛒")
        clean = self.clean_url(str(url))
        if not clean:
            return ""

        info_line = self._format_game_info_line(info)

        display_name = STORE_DISPLAY_NAMES.get(store.lower(), store)

        if store.lower() == "itch":
            slug_name = self._game_name_from_url(clean)
            link_text = self.escape_html(slug_name) if slug_name else self.escape_html(display_name)
        else:
            link_text = self.escape_html(display_name)

        link_html = f'{emoji} <a href="{self.escape_html(clean)}">{link_text}</a>'

        if info and store.lower() in ("steam", "epicgames") and info.name:
            game_name = self.escape_html(info.name)
            if info_line:
                return f"{link_html} — {game_name} — {info_line}"
            return f"{link_html} — {game_name}"

        if info_line:
            return f"{link_html} — {info_line}"
        return link_html

    # ── Store section formatting ──────────────────────────────────────────

    def _format_store_links(self, post: Post) -> str:
        """Format store links section, including prices and game info."""
        if not post.metadata or not post.metadata.store_links:
            return ""

        store_links = post.metadata.store_links
        game_info_map = post.metadata.game_info or {}

        is_bundle = any(len(v) > 1 for v in store_links.values())

        entries = []
        for store, urls in store_links.items():
            display_name = STORE_DISPLAY_NAMES.get(store.lower(), store)
            infos_raw = game_info_map.get(store)

            for i, url in enumerate(urls):
                if isinstance(infos_raw, list):
                    raw = infos_raw[i] if i < len(infos_raw) else None
                else:
                    raw = infos_raw if len(urls) == 1 else None
                info = self._load_game_info(raw)

                label = f"{display_name} {i + 1}" if len(urls) > 1 else display_name
                entry = self._format_one_store_entry(store, url, info, label)
                if entry:
                    entries.append(entry)

        if not entries:
            return ""
        separator = "\n" if is_bundle else " | "
        return separator.join(entries)

    # ── Main formatter ────────────────────────────────────────────────────

    def format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки."""
        try:
            # Header: Title linked with game emoji
            title_link = f'<b>🎮 <a href="{self.escape_html(str(post.link))}">{self.escape_html(post.title)}</a></b>'

            # Content: Smart truncation at sentence boundary
            cleaned_content = self.clean_text(post.content, final_clean=True)
            escaped_content = self.escape_html(cleaned_content)
            content_display = self._truncate_content(escaped_content, max_len=600)

            # Meta Line: Date | Rating | Views
            meta_parts = []
            if post.metadata:
                if post.metadata.date:
                    meta_parts.append(f"📅 {self.format_date(post.metadata.date)}")
                if post.metadata.rating is not None:
                    meta_parts.append(f"⭐ {post.metadata.rating}")
                if post.metadata.views:
                    meta_parts.append(f"👁 {post.metadata.views}")

            meta_line = " | ".join(meta_parts) if meta_parts else ""

            # Store Links (with prices and game info)
            stores_section = self._format_store_links(post)

            # Tags (Hashtags) — support Cyrillic, replace spaces with _
            tags_line = ""
            if post.metadata and post.metadata.tags:
                clean_tags = [re.sub(r"[^\w\u0400-\u04FF]", "", t.replace(" ", "_")) for t in post.metadata.tags]
                tags_line = " ".join([f"#{t}" for t in clean_tags if t])

            # #free tag if any store has is_free=True
            if post.metadata and post.metadata.game_info:
                is_any_free = any(
                    GameInfo.from_dict(info).is_free
                    for info in (post.metadata.game_info or {}).values()
                    if isinstance(info, dict) and info
                )
                if is_any_free and "free" not in tags_line:
                    tags_line = "#free " + tags_line if tags_line else "#free"

            # Footer
            source_name = self.escape_html(post.source) if post.source else "GamesParser"
            footer = f"🤖 GamesParser | {source_name}"

            # Assemble Message
            message_parts = [
                title_link,
                "",
                content_display,
                "",
                meta_line,
                stores_section,
                tags_line,
                "",
                footer,
            ]

            return "\n".join(filter(None, message_parts))

        except Exception as e:
            logger.error("Error formatting message: %s", str(e), exc_info=True)
            return f"Error formatting message: {post.link}"
