"""Message formatting utilities for GamesParser bot."""

import html
import logging
import re
from typing import Optional
from urllib.parse import urlparse

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


CAPTION_LIMIT = 1024

# Store order for links/labels; the first available one is the default giveaway store
_STORE_ORDER = ["steam", "epicgames", "gog", "itch"]
_STORE_TAGS = {
    "steam": "#steam", "epicgames": "#epicgames", "gog": "#gog", "itch": "#itchio",
    "ubisoft": "#ubisoft", "ea": "#ea", "amazon": "#primegaming", "indiegala": "#indiegala",
}
# How headlines name the store where a giveaway happens
_STORE_MENTIONS = [
    ("epicgames", re.compile(r"epic\s*games|\begs\b", re.IGNORECASE)),
    ("gog", re.compile(r"\bgog\b", re.IGNORECASE)),
    ("itch", re.compile(r"itch\.?io", re.IGNORECASE)),
    # Stores we never get links for — a mention alone decides
    ("ubisoft", re.compile(r"ubisoft", re.IGNORECASE)),
    ("ea", re.compile(r"\bea\s*app\b|\borigin\b", re.IGNORECASE)),
    ("amazon", re.compile(r"prime\s*gaming|amazon", re.IGNORECASE)),
    ("indiegala", re.compile(r"indiegala", re.IGNORECASE)),
    ("steam", re.compile(r"steam", re.IGNORECASE)),
]
_LINKLESS_STORE_NAMES = {
    "ubisoft": "Ubisoft Connect", "ea": "EA app", "amazon": "Prime Gaming", "indiegala": "IndieGala",
}

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_DEADLINE_RE = re.compile(
    r"\bдо\s+(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b(?:[^.\n]{0,15}?(\d{1,2}:\d{2}))?",
    re.IGNORECASE,
)
# Steam BBCode markup in reviews/descriptions: [b], [/i], [url=...], [h1], [*]
_BBCODE_RE = re.compile(r"\[/?(?:b|i|u|s|h[1-6]|url|spoiler|quote|list|olist|\*|strike|code|hr|table|tr|td|th|noparse)(?:=[^\]]*)?\]", re.IGNORECASE)
# Pikabu/VGTimes page chrome that leaks into post text
_BOILERPLATE_RE = re.compile(r"Показать полностью(?:\s*\d+)?|Перейти к видео|\b\d+/\d+\b(?=\s*•)", re.IGNORECASE)


class MessageFormatter:
    """Class for formatting messages and URLs for TelegramNewsBot."""

    _HEADERS_FREE = {
        "steam":      "🎁 Игра раздаётся бесплатно в Steam!",
        "egs":        "🎁 Игра стала бесплатной в Epic Games Store!",
        "epicgames":  "🎁 Игра стала бесплатной в Epic Games Store!",
        "gog":        "🎁 Бесплатная игра в GOG!",
        "indiegala":  "🎁 Бесплатная игра в IndieGala!",
        "ubisoft":    "🎁 Бесплатная игра в Ubisoft Connect!",
        "ea":         "🎁 Бесплатная игра в EA App!",
        "fanatical":  "🎁 Бесплатная игра в Fanatical!",
        "amazon":     "🎁 Бесплатная игра в Amazon Prime Gaming!",
        "humble":     "🎁 Бесплатная игра в Humble Bundle!",
        "itch":       "🎁 Бесплатная игра на itch.io!",
        "gamerpower": "🎁 Бесплатная игра!",
    }
    _TAGS_FREE = {
        "steam":      "#free #steam #бесплатно",
        "egs":        "#free #epic #epicgames #бесплатно",
        "epicgames":  "#free #epic #epicgames #бесплатно",
        "gog":        "#free #gog #бесплатно",
        "indiegala":  "#free #indiegala #бесплатно",
        "ubisoft":    "#free #ubisoft #бесплатно",
        "ea":         "#free #ea #origin #бесплатно",
        "fanatical":  "#free #fanatical #бесплатно",
        "amazon":     "#free #amazon #primegaming #бесплатно",
        "humble":     "#free #humblebundle #бесплатно",
        "itch":       "#free #itchio #бесплатно",
        "gamerpower": "#free #бесплатно",
    }
    _HEADERS_DISCOUNT = {
        "egs":       "💥 Большая скидка в Epic Games Store!",
        "epicgames": "💥 Большая скидка в Epic Games Store!",
    }
    _TAGS_DISCOUNT = {
        "egs":       "#скидка #epic #epicgames",
        "epicgames": "#скидка #epic #epicgames",
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

    def escape_html(self, text: str) -> str:
        """Экранирует специальные HTML-символы."""
        text_str = str(text) if not isinstance(text, str) else text
        return html.escape(text_str)

    def to_plain_text(self, html_text: str) -> str:
        """Converts HTML text to plain text by removing tags and unescaping entities."""
        plain_text = re.sub(re.compile("<.*?>"), "", html_text)
        return html.unescape(plain_text)

    # ── Game info helpers ─────────────────────────────────────────────────

    def _format_game_details(self, game_info) -> list[str]:
        """Return formatted lines for genre, metacritic, review score, recommendations,
        languages, controller support, multiplayer, and top reviews."""
        parts = []

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

        reviews = getattr(game_info, "top_reviews", None) or []
        for review_text in reviews[:2]:
            review_text = _BBCODE_RE.sub("", html.unescape(review_text))  # Steam reviews use [b]…[/b]
            review_text = re.sub(r"\s+", " ", review_text).strip()
            truncated = review_text[:120].rstrip()
            if len(review_text) > 120:
                truncated += "…"
            parts.append(f'💬 "{self.escape_html(truncated)}"')

        return parts


    # ── Main formatter ────────────────────────────────────────────────────

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
        worth: Optional[str] = None,
    ) -> str:
        """Format a price alert message for Steam, EGS or a free-games service.

        alert_type: 'became_free' | 'big_discount'
        store: 'steam' | 'egs'
        Prices are in UAH kopecks.
        """
        def fmt_uah(kopecks: Optional[int]) -> str:
            if kopecks is None:
                return "?"
            if kopecks == 0:
                return "Бесплатно"
            return f"₴{kopecks // 100:,}".replace(",", "\u00a0")

        safe_name = self.escape_html(name)
        safe_url = self.escape_html(url)
        name_link = f'<a href="{safe_url}">{safe_name}</a>'

        store_lower = store.lower()

        if alert_type == "became_free":
            header = self._HEADERS_FREE.get(store_lower, "🎁 Игра стала бесплатной!")
            orig_kopecks = original_price_uah or old_price_uah or 0
            if orig_kopecks > 0:
                old_fmt = fmt_uah(orig_kopecks)
                saving_fmt = fmt_uah(orig_kopecks)
                price_line = f"💰 Цена: <s>{old_fmt}</s> → Бесплатно (экономия {saving_fmt})"
            else:
                price_line = "💰 Цена: Бесплатно"
            tags = self._TAGS_FREE.get(store_lower, "#free #бесплатно")
        else:
            header = self._HEADERS_DISCOUNT.get(store_lower, "💥 Большая скидка в Steam!")
            orig_fmt = fmt_uah(original_price_uah)
            new_fmt = fmt_uah(new_price_uah)
            saving_kopecks = (original_price_uah or 0) - new_price_uah
            saving_fmt = fmt_uah(saving_kopecks)
            price_line = f"💰 {orig_fmt} → {new_fmt} (-{discount_pct}%, экономия {saving_fmt})"
            tags = self._TAGS_DISCOUNT.get(store_lower, "#скидка #steam")

        if worth and alert_type == "became_free" and not (original_price_uah or old_price_uah):
            price_line = f"💰 Цена: <s>{self.escape_html(worth)}</s> → Бесплатно"

        desc_source = short_description
        if not desc_source and game_info and getattr(game_info, "short_description", None):
            desc_source = game_info.short_description

        cross_block = None
        if cross_store_data and cross_store_data.get("url"):
            cross_label = "Также в Steam" if cross_store_data.get("store") == "steam" else "Также в Epic Games Store"
            cross_link = f'<a href="{self.escape_html(cross_store_data["url"])}">{cross_label}</a>'
            cross_price_line = (
                f"💰 {fmt_uah(cross_store_data.get('original_price_uah'))} → "
                f"{fmt_uah(cross_store_data.get('price_uah'))} (-{cross_store_data.get('discount_pct') or 0}%)"
            )
            cross_block = f"━━━━━━━━━━\n🔗 {cross_link}\n{cross_price_line}"

        def build(level: int) -> str:
            parts = [header, f"🎮 {name_link}"]
            desc = self._clean_description(desc_source, (180, 180, 140, 100, 60, 0)[level])
            if desc:
                parts.append(f"\n📝 {self.escape_html(desc)}")
            parts.append(price_line)
            if game_info and level < 4:
                details = self._format_game_details(game_info)
                reviews = [d for d in details if d.startswith('💬 "')]
                other = [d for d in details if not d.startswith('💬 "')]
                parts.extend(other + reviews[: (2, 1, 0, 0)[level]])
            parts.append(tags)
            if cross_block:
                parts.append(cross_block)
            return "\n".join(parts)

        # Telegram caption limit for photos is 1024 visible chars
        return self._fit_caption(build)

    # ── Estate alert (one message per game event, all sources merged) ──────

    def _clean_description(self, text: Optional[str], max_len: int) -> str:
        """Unescape (store APIs return HTML entities), drop URLs/boilerplate and trim at a sentence/word boundary."""
        if not text:
            return ""
        text = html.unescape(html.unescape(text))
        text = re.sub(r"<[^>]+>", " ", text)
        text = _BBCODE_RE.sub("", text)
        text = re.sub(r"https?://\S+", "", text)
        text = _BOILERPLATE_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip(" |")
        text = re.sub(r"\s+([.,!?:;])", r"\1", text)
        if len(text) <= max_len:
            return text
        snippet = text[:max_len]
        cut = max(snippet.rfind(". "), snippet.rfind("! "), snippet.rfind("? "))
        if cut >= max_len // 2:
            return snippet[:cut + 1]
        cut = snippet.rfind(" ")
        return (snippet[:cut] if cut > 0 else snippet).rstrip(",;:— -") + "…"

    def _extract_deadline(self, *texts: str) -> Optional[str]:
        """'Раздача продлится до 1 октября' → 'до 1 октября'."""
        for text in texts:
            m = _DEADLINE_RE.search(text or "")
            if m:
                day, month, time_str = m.group(1), m.group(2).lower(), m.group(3)
                result = f"до {int(day)} {month}"
                return f"{result}, {time_str}" if time_str else result
        return None

    @staticmethod
    def _free_store(estate: dict, games: list[dict]) -> Optional[str]:
        """Store where the giveaway happens: mentioned in a headline, else the best available store."""
        headlines = " ".join([estate.get("title", "")] + [p.get("title", "") for p in estate.get("posts", [])])
        available = {s for g in games for s in g.get("links", {})}
        for store, pattern in _STORE_MENTIONS:
            if pattern.search(headlines) and (store in available or not available or store in _LINKLESS_STORE_NAMES):
                return store
        return next((s for s in _STORE_ORDER if s in available), None)

    def _store_links_line(self, links: dict) -> str:
        parts = []
        for store in sorted(links, key=lambda s: _STORE_ORDER.index(s) if s in _STORE_ORDER else 99):
            url = self.clean_url(links[store])
            if url:
                label = f"{STORE_EMOJIS.get(store, '🛒')} {STORE_DISPLAY_NAMES.get(store, store)}"
                parts.append(f'<a href="{self.escape_html(url)}">{self.escape_html(label)}</a>')
        return " · ".join(parts)

    def _sources_line(self, posts: list) -> str:
        links, seen = [], set()
        for p in posts:
            source, link = p.get("source", ""), p.get("post_link", "")
            if source and link and source not in seen:
                seen.add(source)
                links.append(f'<a href="{self.escape_html(link)}">{self.escape_html(source)}</a>')
        return "📰 " + " · ".join(links) if links else ""

    @staticmethod
    def _estate_tags(is_free: bool, stores: list[str], mobile: bool) -> str:
        tags = ["#free", "#бесплатно"] if is_free else ["#скидка"]
        tags += [_STORE_TAGS[s] for s in stores if s in _STORE_TAGS]
        if mobile:
            tags.append("#mobile")
        return " ".join(dict.fromkeys(tags))

    def _price_line(self, info: Optional[GameInfo], is_free: bool) -> Optional[str]:
        if is_free:
            regular = None
            if info:
                regular = info.original_price or (info.price if not info.is_free else None)
            if regular and regular != "Бесплатно":
                return f"💰 <s>{self.escape_html(regular)}</s> → <b>Бесплатно</b>"
            return "💰 <b>Бесплатно</b>"
        if info:
            price = info.format_price()
            return f"💰 {price}" if price else None
        return None

    def _fit_caption(self, build, limit: int = CAPTION_LIMIT) -> str:
        """Call build(level) with growing compaction levels until the visible text fits the caption limit."""
        text = ""
        for level in range(6):
            text = build(level)
            if len(self.to_plain_text(text)) <= limit:
                return text
        return text  # the bot falls back to plain text in this unlikely case

    def format_estate_alert(self, estate: dict, game_info: Optional[GameInfo] = None) -> str:
        """Format one estate (a game event gathered from all sources) as a Telegram caption.

        Three layouts: a single game card, a list of games, or a headline-only news item
        when no store links could be found.
        """
        games: list[dict] = estate.get("games") or []
        is_free: bool = bool(estate.get("is_free"))
        posts: list = estate.get("posts") or []
        mobile = str(estate.get("kind", "")).endswith("mobile")
        store = self._free_store(estate, games)
        stores = list(dict.fromkeys(([store] if store else []) + [s for g in games for s in g.get("links", {})]))
        source_text = estate.get("description", "")
        deadline = self._extract_deadline(source_text, estate.get("title", ""))
        sources = self._sources_line(posts)
        # A giveaway is tagged with the store that gives it away, a deal with every store it links to
        tags = self._estate_tags(is_free, [store] if (is_free and store) else stores, mobile)
        store_name = (STORE_DISPLAY_NAMES.get(store) or _LINKLESS_STORE_NAMES.get(store, "")) if store else ""

        if len(games) == 1:
            game = games[0]
            info, info_store = game_info, "steam" if game_info else None
            if info is None:
                info_store, raw = next(((s, i) for s, i in game.get("info", {}).items() if i), (None, None))
                info = GameInfo.from_dict(raw) if raw else None
            # A crossed-out price is only honest when it comes from the store that gives the game away
            price_info = info if (not is_free or info_store == store) else None
            name = (info.name if info and info.name else None) or game.get("name") or estate.get("title", "")
            links_map = game.get("links", {})
            main_url = self.clean_url(links_map.get(store) or next(iter(links_map.values()), None)
                                      or (posts[0].get("post_link") if posts else "") or "")
            if is_free:
                header = f"🎁 <b>Бесплатно в {self.escape_html(store_name)}</b>" if store_name else "🎁 <b>Бесплатная раздача</b>"
            else:
                header = f"🔥 <b>Скидка в {self.escape_html(store_name)}</b>" if store_name else "🔥 <b>Скидка</b>"
            title_line = (f'🎮 <b><a href="{self.escape_html(main_url)}">{self.escape_html(name)}</a></b>' if main_url
                          else f"🎮 <b>{self.escape_html(name)}</b>")
            game_desc = info.short_description if info and info.short_description else ""
            # Steam falls back to English when a game has no Russian text — the source's Russian text reads better
            if source_text and not re.search(r"[А-Яа-яЁё]", game_desc):
                game_desc = ""

            def build(level: int) -> str:
                desc_len = (240, 240, 180, 140, 100, 0)[level]
                desc = self._clean_description(game_desc or source_text, desc_len) if desc_len else ""
                parts = [header, title_line]
                if desc:
                    parts += ["", f"📝 {self.escape_html(desc)}"]
                parts.append("")
                price = self._price_line(price_info, is_free)
                if price:
                    parts.append(price)
                if deadline:
                    parts.append(f"⏳ {self.escape_html(deadline)}")
                if info and level < 4:
                    details = self._format_game_details(info)
                    reviews = [d for d in details if d.startswith('💬 "')]
                    other = [d for d in details if not d.startswith('💬 "')]
                    parts += other[: (9, 9, 2, 1)[level]] + reviews[: (1, 0, 0, 0)[level]]
                parts.append("")
                links = self._store_links_line(game.get("links", {}))
                if links:
                    parts.append(f"🛒 {links}")
                if sources:
                    parts.append(sources)
                parts.append(tags)
                return "\n".join(parts)

            return self._fit_caption(build)

        if games:
            count = len(games)
            noun = "игра" if count == 1 else ("игры" if count < 5 else "игр")
            where = f" в {self.escape_html(store_name)}" if store_name else ""
            header = (f"🎁 <b>Бесплатно{where}: {count} {noun}</b>" if is_free
                      else f"🔥 <b>Скидки{where}: {count} {noun}</b>")

            def build(level: int) -> str:
                desc_len = (220, 160, 120, 0, 0, 0)[level]
                max_games = (15, 15, 12, 10, 8, 5)[level]
                parts = [header, ""]
                for game in games[:max_games]:
                    name = self.escape_html(game.get("name") or "")
                    links = self._store_links_line(game.get("links", {}))
                    if name and links:
                        parts.append(f"• <b>{name}</b> — {links}")
                    elif name or links:  # an unnamed game (bare store link) is shown by its link alone
                        parts.append(f"• <b>{name}</b>" if name else f"• {links}")
                if len(games) > max_games:
                    parts.append(f"…и ещё {len(games) - max_games}")
                desc = self._clean_description(source_text, desc_len) if desc_len else ""
                if desc:
                    parts += ["", f"📝 {self.escape_html(desc)}"]
                if deadline:
                    parts += ["", f"⏳ {self.escape_html(deadline)}"]
                parts.append("")
                if sources:
                    parts.append(sources)
                parts.append(tags)
                return "\n".join(parts)

            return self._fit_caption(build)

        # No store links at all — a news-style item linking to the sources
        headline = self.escape_html(estate.get("title", ""))
        first_link = posts[0].get("post_link") if posts else None
        icon = "🎁" if is_free else "📰"
        header = f'{icon} <b><a href="{self.escape_html(first_link)}">{headline}</a></b>' if first_link \
            else f"{icon} <b>{headline}</b>"

        def build(level: int) -> str:
            desc_len = (400, 300, 220, 150, 100, 0)[level]
            parts = [header]
            desc = self._clean_description(source_text, desc_len) if desc_len else ""
            if desc:
                parts += ["", self.escape_html(desc)]
            if deadline:
                parts += ["", f"⏳ {self.escape_html(deadline)}"]
            parts.append("")
            if sources and len({p.get("source") for p in posts}) > 1:  # a single source is already the headline link
                parts.append(sources)
            parts.append(tags)
            return "\n".join(parts)

        return self._fit_caption(build)
