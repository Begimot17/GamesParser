"""Telegram bot logic for GamesParser project."""

import asyncio
from typing import Optional

import httpx
from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode

from src.bot.message_formatter import MessageFormatter
from src.bot.retry_handler import RetryHandler
from src.common.logger import logger
from src.models.models import Post # Keep Post import for type hinting if needed elsewhere, but not for dummy creation here
from src.storage.telegram_storage import TelegramStorage


class TelegramNewsBot:
    """Telegram bot for sending news posts to a channel."""

    def __init__(self, token: str, channel_id: str, config: Optional[dict] = None):
        logger.info(f"[TelegramNewsBot] Initializing bot for channel {channel_id}")
        if not token or not channel_id:
            raise ValueError("Token and channel_id must be provided.")

        self.token = token.split("#")[0].strip()
        self.channel_id = channel_id
        self.config = self._get_default_config(config)

        self.bot = Bot(token=self.token)
        self.http_client = self._init_http_client()
        self.retry_handler = self._init_retry_handler()
        self.formatter = MessageFormatter()
        self.telegram_storage = TelegramStorage()

    def _get_default_config(self, config: Optional[dict]) -> dict:
        """Возвращает конфигурацию по умолчанию, обновленную пользовательской конфигурацией."""
        defaults = {
            "message_delay": 30,
            "retry_delay": 30,
            "max_retries": 5,
            "max_images": 10,
            "validate_images": True,
        }
        return {**defaults, **(config or {})}

    def _init_http_client(self) -> httpx.AsyncClient:
        """Инициализирует и возвращает HTTP-клиент."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            transport=httpx.AsyncHTTPTransport(retries=3),
        )

    def _init_retry_handler(self) -> RetryHandler:
        """Инициализирует и возвращает обработчик повторных попыток."""
        return RetryHandler(
            config={
                "max_retries": self.config["max_retries"],
                "base_delay": self.config["retry_delay"],
            },
        )

    async def close(self):
        """Закрывает сессию бота."""
        logger.info("[TelegramNewsBot] Closing bot session...")
        if self.http_client:
            await self.http_client.aclose()
        logger.info("[TelegramNewsBot] Bot session closed.")

    async def send_message(self, text: str, images: Optional[list[str]] = None) -> bool:
        """Отправляет сообщение в канал, выбирая подходящий метод."""
        if images:
            success = await self._send_media_group_message(text, images)
        else:
            success = await self._send_text_message(text)

        if success:
            self.telegram_storage.save_message(text, self.channel_id)
        return success

    async def _send_text_message(self, text: str) -> bool:
        """Отправляет текстовое сообщение."""
        # 'text' is already the fully formatted HTML message from formatter.format_message
        message_content = text
        
        parse_mode = ParseMode.HTML
        if len(message_content) > 4096: # Telegram text message limit
            logger.warning(f"[TelegramNewsBot] Text message too long ({len(message_content)} chars), converting to plain text.")
            message_content = self.formatter.to_plain_text(message_content)[:4096] # Truncate plain text
            parse_mode = None # Send as plain text

        logger.info(f"[TelegramNewsBot] Sending text message (first 500 chars): {message_content[:500]}")
        result = await self.retry_handler.run_with_retry(
            self.bot.send_message,
            chat_id=self.channel_id,
            text=message_content,
            parse_mode=parse_mode,
        )
        return bool(result)

    async def _send_media_group_message(self, text: str, images: list[str]) -> bool:
        """Отправляет сообщение с группой медиа."""
        media_group = await self._prepare_media_group(text, images)
        if not media_group:
            logger.warning("TelegramNewsBot No valid images to send")
            return False

        max_media_per_group = 10
        if len(media_group) > max_media_per_group:
            return await self._send_large_media_group(media_group)
        else:
            # Log the caption for the first media item
            if media_group and media_group[0].caption:
                logger.info(f"[TelegramNewsBot] Sending media group with caption (first 500 chars): {media_group[0].caption[:500]}")
            result = await self.retry_handler.run_with_retry(
                self.bot.send_media_group,
                chat_id=self.channel_id,
                media=media_group,
            )
            return bool(result)

    async def _prepare_media_group(self, text: str, images: list[str]) -> list[InputMediaPhoto]:
        """Подготавливает список медиа для отправки."""
        media_group = []
        
        # 'text' is already the fully formatted HTML message from formatter.format_message
        caption_html = text
        caption_plain = self.formatter.to_plain_text(caption_html)

        parse_mode = ParseMode.HTML
        caption_to_send = caption_html

        if len(caption_html) > 1024: # Telegram media caption limit
            logger.warning(f"[TelegramNewsBot] Media caption too long ({len(caption_html)} chars), converting to plain text.")
            caption_to_send = caption_plain[:1021] + "..." if len(caption_plain) > 1024 else caption_plain # Truncate plain text
            parse_mode = None # Send as plain text
        
        for i, image_url in enumerate(images[: self.config["max_images"]]):
            clean_url = self.formatter.clean_url(image_url)
            if not clean_url or (self.config["validate_images"] and not await self._validate_image_url(clean_url)):
                logger.warning(f"Skipping invalid or unavailable image URL: {image_url}")
                continue

            media_group.append(
                InputMediaPhoto(
                    media=clean_url,
                    caption=caption_to_send if i == 0 else None,
                    parse_mode=parse_mode,
                ),
            )
        return media_group

    async def _send_large_media_group(self, media_group: list[InputMediaPhoto]) -> bool:
        """Отправляет большую медиагруппу по частям."""
        logger.info(f"Splitting large media group ({len(media_group)} items)")
        max_media_per_group = 10
        for i in range(0, len(media_group), max_media_per_group):
            group_slice = media_group[i : i + max_media_per_group]
            if i > 0:
                for media in group_slice:
                    media.caption = None
                    media.parse_mode = None # Ensure subsequent captions are plain text if first was

            # Log the caption for the first media item in the slice
            if group_slice and group_slice[0].caption:
                logger.info(f"[TelegramNewsBot] Sending large media group slice with caption (first 500 chars): {group_slice[0].caption[:500]}")
            result = await self.retry_handler.run_with_retry(
                self.bot.send_media_group,
                chat_id=self.channel_id,
                media=group_slice,
            )
            if not result:
                return False
            await asyncio.sleep(2)
        return True

    async def _validate_image_url(self, url: str) -> bool:
        """Проверяет доступность изображения по URL."""
        try:
            response = await self.http_client.head(url, timeout=10.0)
            return response.status_code == 200 and "image" in response.headers.get("content-type", "")
        except Exception as e:
            logger.warning(f"Error validating image URL {url}: {e}")
            return False

    def _format_message(self, post: Post) -> str:
        """Форматирует сообщение для отправки."""
        return self.formatter.format_message(post)
