"""Telegram bot command handlers for GamesParser."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from src.config.config import settings

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from src.storage.sqlite_storage import SQLiteStorage

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    """Return True if user_id is allowed to use commands.

    If ADMIN_USER_IDS is empty, all users are allowed.
    """
    if not settings.ADMIN_USER_IDS:
        return True
    return user_id in settings.ADMIN_USER_IDS


class CommandHandler:
    """Handles /stats, /recent, /retry bot commands."""

    def __init__(self, storage: "SQLiteStorage", monitor) -> None:
        self.storage = storage
        self.monitor = monitor

    async def cmd_stats(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Reply with aggregate statistics from the posts log."""
        if not _is_admin(update.effective_user.id):
            return

        try:
            stats = await self.storage.get_posts_stats()
            lines = [
                "<b>📊 Статистика GamesParser</b>",
                f"Всього постів: <b>{stats.get('total', 0)}</b>",
                f"Відправлено: <b>{stats.get('sent', 0)}</b>",
                f"Безкоштовних: <b>{stats.get('is_free', 0)}</b>",
            ]
            by_source = stats.get("by_source", {})
            if by_source:
                lines.append("\nЗа джерелами:")
                for src, cnt in by_source.items():
                    lines.append(f"  • {html.escape(src)}: {cnt}")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.error("[CommandHandler] /stats failed: %s", e, exc_info=True)
            await update.message.reply_text("Помилка при отриманні статистики.")

    async def cmd_recent(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Reply with the 5 most recently sent posts."""
        if not _is_admin(update.effective_user.id):
            return

        try:
            posts = await self.storage.get_recent_posts(limit=5)
            if not posts:
                await update.message.reply_text("Ще немає відправлених постів.")
                return
            lines = ["<b>🕐 Останні пости</b>"]
            for p in posts:
                title = html.escape(p.get("title") or "—")
                link = html.escape(p.get("link") or "")
                source = html.escape(p.get("source") or "?")
                sent_at = p.get("sent_at") or "?"
                lines.append(f'• [{source}] <a href="{link}">{title}</a> — {sent_at}')
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.error("[CommandHandler] /recent failed: %s", e, exc_info=True)
            await update.message.reply_text("Помилка при отриманні останніх постів.")

    async def cmd_retry(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Trigger DLQ retry immediately."""
        if not _is_admin(update.effective_user.id):
            return

        try:
            failed = await self.storage.get_failed_posts(max_retries=3)
            if not failed:
                await update.message.reply_text("DLQ порожня — немає постів для повтору.")
                return
            await update.message.reply_text(f"⏳ Повторна спроба для {len(failed)} постів…")
            await self.monitor._retry_failed_posts()
            await update.message.reply_text("✅ Retry завершено.")
        except Exception as e:
            logger.error("[CommandHandler] /retry failed: %s", e, exc_info=True)
            await update.message.reply_text("Помилка при повторній спробі.")
