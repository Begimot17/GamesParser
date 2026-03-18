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

    _HEADERS_FREE = {
        "steam":      "🎁 Гра роздається безкоштовно на Steam!",
        "egs":        "🎁 Гра стала безкоштовною на Epic Games Store!",
        "epicgames":  "🎁 Гра стала безкоштовною на Epic Games Store!",
        "gog":        "🎁 Безкоштовна гра на GOG!",
        "indiegala":  "🎁 Безкоштовна гра на IndieGala!",
        "ubisoft":    "🎁 Безкоштовна гра в Ubisoft Connect!",
        "ea":         "🎁 Безкоштовна гра в EA App!",
        "fanatical":  "🎁 Безкоштовна гра на Fanatical!",
        "amazon":     "🎁 Безкоштовна гра в Amazon Prime Gaming!",
        "humble":     "🎁 Безкоштовна гра на Humble Bundle!",
        "gamerpower": "🎁 Безкоштовна гра (GamerPower)!",
    }
    _TAGS_FREE = {
        "steam":      "#free #steam #безкоштовно",
        "egs":        "#free #epic #epicgames #безкоштовно",
        "epicgames":  "#free #epic #epicgames #безкоштовно",
        "gog":        "#free #gog #безкоштовно",
        "indiegala":  "#free #indiegala #безкоштовно",
        "ubisoft":    "#free #ubisoft #безкоштовно",
        "ea":         "#free #ea #origin #безкоштовно",
        "fanatical":  "#free #fanatical #безкоштовно",
        "amazon":     "#free #amazon #primegaming #безкоштовно",
        "humble":     "#free #humblebundle #безкоштовно",
        "gamerpower": "#free #безкоштовно",
    }
    _HEADERS_DISCOUNT = {
        "egs":       "💥 Велика знижка на Epic Games Store!",
        "epicgames": "💥 Велика знижка на Epic Games Store!",
    }
    _TAGS_DISCOUNT = {
        "egs":       "#знижка #epic #epicgames",
        "epicgames": "#знижка #epic #epicgames",
    }

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

    def format_price_alert(
        self,
        name: str,
        url: str,
        old_price_uah: Optional[int],
        new_price_uah: int,
        original_price_uah: Optional[int],
        discount_pct: int,
        alert_type: str,
        game_info=None,
        store: str = "steam",
        cross_store_data: Optional[dict] = None,
        short_description: Optional[str] = None,
    ) -> str:
        """Format a price alert message for Steam or EGS.

        alert_type: 'became_free' | 'big_discount'
        store: 'steam' | 'egs'
        Prices are in UAH kopecks.
        """
        def fmt_uah(kopecks: Optional[int]) -> str:
            if kopecks is None:
                return "?"
            if kopecks == 0:
                return "Безкоштовно"
            return f"₴{kopecks // 100:,}".replace(",", "\u00a0")

        safe_name = self.escape_html(name)
        safe_url = self.escape_html(url)
        name_link = f'<a href="{safe_url}">{safe_name}</a>'

        store_lower = store.lower()

        if alert_type == "became_free":
            header = self._HEADERS_FREE.get(store_lower, "🎁 Гра стала безкоштовною!")
            orig_kopecks = original_price_uah or old_price_uah or 0
            old_fmt = fmt_uah(orig_kopecks)
            saving_fmt = fmt_uah(orig_kopecks)
            price_line = f"💰 Ціна: <s>{old_fmt}</s> → Безкоштовно (зниження на {saving_fmt})"
            tags = self._TAGS_FREE.get(store_lower, "#free #steam #безкоштовно")
        else:
            header = self._HEADERS_DISCOUNT.get(store_lower, "💥 Велика знижка на Steam!")
            orig_fmt = fmt_uah(original_price_uah)
            new_fmt = fmt_uah(new_price_uah)
            saving_kopecks = (original_price_uah or 0) - new_price_uah
            saving_fmt = fmt_uah(saving_kopecks)
            price_line = f"💰 {orig_fmt} → {new_fmt} (-{discount_pct}%, знижка {saving_fmt})"
            tags = self._TAGS_DISCOUNT.get(store_lower, "#знижка #steam")

        parts = [header, f"🎮 {name_link}"]

        # Short description (truncated to 180 chars)
        desc = short_description
        if not desc and game_info and getattr(game_info, "short_description", None):
            desc = game_info.short_description
        if desc:
            desc_truncated = desc[:180] + "…" if len(desc) > 180 else desc
            parts.append(f"\n📝 {self.escape_html(desc_truncated)}")

        parts.append(price_line)

        if game_info:
            # Genre + rating + recommendations count
            meta_parts = []
            if game_info.genre:
                meta_parts.append(f"🎭 {self.escape_html(game_info.genre)}")
            if game_info.metacritic is not None:
                meta_parts.append(f"⭐ Metacritic: {game_info.metacritic}")
            if getattr(game_info, "review_score", None):
                meta_parts.append(self.escape_html(game_info.review_score))
            recs = getattr(game_info, "recommendations_total", None)
            if recs:
                meta_parts.append(f"👍 {recs:,}".replace(",", "\u00a0"))
            if meta_parts:
                parts.append(" | ".join(meta_parts))

            # Languages and features line
            feat_parts = []
            lang_parts = []
            if getattr(game_info, "has_russian_audio", False):
                lang_parts.append("RU🔊")
            elif getattr(game_info, "has_russian_text", False):
                lang_parts.append("RU")
            if getattr(game_info, "has_ukrainian_audio", False):
                lang_parts.append("UA🔊")
            elif getattr(game_info, "has_ukrainian_text", False):
                lang_parts.append("UA")
            if lang_parts:
                feat_parts.append("🌐 " + " ".join(lang_parts))
            if getattr(game_info, "has_controller_support", False):
                feat_parts.append("🕹 Геймпад")
            if getattr(game_info, "has_multiplayer", False):
                feat_parts.append("👥 Мультиплеер")
            if feat_parts:
                parts.append(" | ".join(feat_parts))

            # Top reviews (up to 2, truncated to 120 chars each)
            reviews = getattr(game_info, "top_reviews", None) or []
            for review_text in reviews[:2]:
                truncated = review_text[:120].rstrip()
                if len(review_text) > 120:
                    truncated += "…"
                parts.append(f'💬 "{self.escape_html(truncated)}"')

        parts.append(tags)

        if cross_store_data:
            cross_store = cross_store_data.get("store", "")
            cross_url = cross_store_data.get("url", "")
            cross_price = cross_store_data.get("price_uah")
            cross_original = cross_store_data.get("original_price_uah")
            cross_discount = cross_store_data.get("discount_pct") or 0

            if cross_url:
                if cross_store == "steam":
                    cross_label = "Також у Steam"
                else:
                    cross_label = "Також в Epic Games Store"

                cross_link = f'<a href="{self.escape_html(cross_url)}">{cross_label}</a>'
                cross_price_line = f"💰 {fmt_uah(cross_original)} → {fmt_uah(cross_price)} (-{cross_discount}%)"
                parts.append(f"━━━━━━━━━━\n🔗 {cross_link}\n{cross_price_line}")

        result = "\n".join(parts)
        # Telegram caption limit for photos is 1024 chars
        if len(result) > 1024:
            result = result[:1021] + "…"
        return result
