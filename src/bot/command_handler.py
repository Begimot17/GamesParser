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
                f"Всего постов: <b>{stats.get('total', 0)}</b>",
                f"Отправлено: <b>{stats.get('sent', 0)}</b>",
                f"Бесплатных: <b>{stats.get('is_free', 0)}</b>",
            ]
            by_source = stats.get("by_source", {})
            if by_source:
                lines.append("\nПо источникам:")
                for src, cnt in by_source.items():
                    lines.append(f"  • {html.escape(src)}: {cnt}")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.error("[CommandHandler] /stats failed: %s", e, exc_info=True)
            await update.message.reply_text("Ошибка при получении статистики.")

    async def cmd_recent(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Reply with the 5 most recently sent posts."""
        if not _is_admin(update.effective_user.id):
            return

        try:
            posts = await self.storage.get_recent_posts(limit=5)
            if not posts:
                await update.message.reply_text("Отправленных постов пока нет.")
                return
            lines = ["<b>🕐 Последние посты</b>"]
            for p in posts:
                title = html.escape(p.get("title") or "—")
                link = html.escape(p.get("link") or "")
                source = html.escape(p.get("source") or "?")
                sent_at = p.get("sent_at") or "?"
                lines.append(f'• [{source}] <a href="{link}">{title}</a> — {sent_at}')
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.error("[CommandHandler] /recent failed: %s", e, exc_info=True)
            await update.message.reply_text("Ошибка при получении последних постов.")

    async def cmd_retry(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        """Trigger DLQ retry immediately."""
        if not _is_admin(update.effective_user.id):
            return

        try:
            failed = await self.storage.get_failed_estates(max_retries=3)
            if not failed:
                await update.message.reply_text("DLQ пуста — нет постов для повтора.")
                return
            await update.message.reply_text(f"⏳ Повторная попытка для {len(failed)} постов…")
            await self.monitor._retry_failed_estates()
            await update.message.reply_text("✅ Повтор завершён.")
        except Exception as e:
            logger.error("[CommandHandler] /retry failed: %s", e, exc_info=True)
            await update.message.reply_text("Ошибка при повторной попытке.")
