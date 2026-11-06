"""Telegram bot logic for GamesParser project."""

import asyncio
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import httpx
from telegram import Bot, InputMediaPhoto, request
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application
from telegram.ext import CommandHandler as TelegramCommandHandler

from src.bot.message_formatter import MessageFormatter
from src.bot.retry_handler import RetryHandler, retry
from src.common.logger import logger

if TYPE_CHECKING:
    from src.bot.command_handler import CommandHandler


CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
PHOTO_UPLOAD_LIMIT = 10 * 1024 * 1024
# Telegram errors meaning it could not download/accept a photo given by URL
_MEDIA_FETCH_ERRORS = (
    "webpage_curl_failed",
    "webpage_media_empty",
    "wrong file identifier",
    "failed to get http url content",
    "wrong type of the web page content",
    "image_process_failed",
    "photo_invalid_dimensions",
)
_IMAGE_CHECK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
}


@dataclass(frozen=True)
class SentMessage:
    """Reference to a sent channel message (truthy), used to edit it later."""

    message_id: int
    is_caption: bool


def _first_message(result: Any) -> Optional[Any]:
    """send_message returns a Message, send_media_group a tuple of Messages."""
    if isinstance(result, (list, tuple)):
        return result[0] if result else None
    return result


def _is_media_fetch_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _MEDIA_FETCH_ERRORS)


class TelegramNewsBot:
    """Telegram bot for posting news updates."""

    def __init__(self, token: str, channel_id: str, config: Optional[dict] = None):
        logger.info("[TelegramNewsBot] Initializing bot for channel %s", channel_id)
        if not token or not channel_id:
            raise ValueError("Token and channel_id must be provided.")

        self.token = token.split("#")[0].strip()
        self.channel_id = channel_id
        self.config = self._get_default_config(config)

        # Initialize Bot with larger connection pool
        request_instance = request.HTTPXRequest(
            connection_pool_size=10,
            read_timeout=30.0,
            write_timeout=30.0,
            connect_timeout=30.0,
            pool_timeout=30.0,
        )
        self.bot = Bot(token=self.token, request=request_instance)

        self.http_client = self._init_http_client()
        self.retry_handler = self._init_retry_handler()
        self.formatter = MessageFormatter()
        self._application: Optional[Application] = None
        self._polling_started: bool = False

    def _get_default_config(self, config: Optional[dict]) -> dict:
        defaults = {
            "message_delay": 30,
            "retry_delay": 30,
            "max_retries": 5,
            "max_images": 10,
            "validate_images": True,
        }
        return {**defaults, **(config or {})}

    def _init_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            transport=httpx.AsyncHTTPTransport(retries=3),
        )

    def _init_retry_handler(self) -> RetryHandler:
        return RetryHandler(
            config={
                "max_retries": self.config["max_retries"],
                "base_delay": self.config["retry_delay"],
            },
        )

    def _get_application(self) -> Application:
        """Lazily build the Application instance (used for command polling)."""
        if self._application is None:
            self._application = Application.builder().token(self.token).build()
        return self._application

    def register_commands(self, handler: "CommandHandler") -> None:
        """Register /stats, /recent, /retry command handlers."""
        app = self._get_application()
        app.add_handler(TelegramCommandHandler("stats", handler.cmd_stats))
        app.add_handler(TelegramCommandHandler("recent", handler.cmd_recent))
        app.add_handler(TelegramCommandHandler("retry", handler.cmd_retry))

    async def start_polling(self) -> None:
        """Start polling for bot commands. Runs until cancelled."""
        app = self._get_application()
        self._polling_started = True
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("[TelegramNewsBot] Command polling started.")
        try:
            await asyncio.Event().wait()  # Block until cancelled
        finally:
            if app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
            self._polling_started = False
            logger.info("[TelegramNewsBot] Command polling stopped.")

    async def close(self):
        logger.info("[TelegramNewsBot] Closing bot session...")
        if self.http_client:
            await self.http_client.aclose()
        logger.info("[TelegramNewsBot] Bot session closed.")

    async def send_message(self, text: str, images: Optional[list[str]] = None) -> Optional[SentMessage]:
        """Sends a message to the channel, choosing the appropriate method.

        Returns a (truthy) SentMessage reference on success, None on failure.
        """
        if images:
            return await self._send_media_group_message(text, images)
        return await self._send_text_message(text)

    async def edit_message(self, ref: SentMessage, text: str) -> bool:
        """Replace the text (or the photo caption) of an already sent message."""
        try:
            if ref.is_caption:
                caption, parse_mode = self._fit_html(text, CAPTION_LIMIT)
                await self.bot.edit_message_caption(
                    chat_id=self.channel_id, message_id=ref.message_id, caption=caption, parse_mode=parse_mode,
                )
            else:
                body, parse_mode = self._fit_html(text, TEXT_LIMIT)
                await self.bot.edit_message_text(
                    chat_id=self.channel_id, message_id=ref.message_id, text=body, parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            logger.info("[TelegramNewsBot] Edited message %s", ref.message_id)
            return True
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return True
            logger.warning("[TelegramNewsBot] Cannot edit message %s: %s", ref.message_id, e)
            return False
        except Exception as e:
            logger.warning("[TelegramNewsBot] Cannot edit message %s: %r", ref.message_id, e)
            return False

    def _fit_html(self, text: str, limit: int) -> tuple[str, Optional[str]]:
        """Telegram limits count visible characters, not HTML markup.

        Keeps HTML when the visible text fits; otherwise falls back to trimmed plain text.
        """
        plain = self.formatter.to_plain_text(text)
        if len(plain) <= limit:
            return text, ParseMode.HTML if "<" in text else None
        logger.warning("[TelegramNewsBot] Message too long (%d visible chars), sending as plain text", len(plain))
        return plain[: limit - 1] + "…", None

    async def _send_text_message(self, text: str) -> Optional[SentMessage]:
        message_content, parse_mode = self._fit_html(text, TEXT_LIMIT)
        logger.info("[TelegramNewsBot] Sending text message (first 500 chars): %s", message_content[:500])
        result = await self.retry_handler.run_with_retry(
            self.bot.send_message,
            chat_id=self.channel_id,
            text=message_content,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        message = _first_message(result)
        return SentMessage(message.message_id, is_caption=False) if message else None

    async def _send_media_group_message(self, text: str, images: list[str]) -> Optional[SentMessage]:
        """Sends a media group with caption."""
        media_group = await self._prepare_media_group(text, images)
        if not media_group:
            logger.warning("[TelegramNewsBot] No valid media to send, falling back to text message")
            return await self._send_text_message(text)

        logger.info(
            "[TelegramNewsBot] Sending media group with caption: %s",
            media_group[0].caption[:500] if media_group[0].caption else "No caption",
        )
        try:
            return await self._send_albums(media_group)
        except BadRequest as e:
            if not _is_media_fetch_error(e):
                raise
            logger.warning("[TelegramNewsBot] Telegram could not fetch images (%s), uploading them ourselves", e)

        uploaded = await self._download_media(media_group)
        if uploaded:
            try:
                return await self._send_albums(uploaded)
            except BadRequest as e:
                logger.warning("[TelegramNewsBot] Upload of images failed (%s)", e)
        logger.warning("[TelegramNewsBot] Falling back to text message")
        return await self._send_text_message(text)

    async def _download_media(self, media_group: list[InputMediaPhoto]) -> list[InputMediaPhoto]:
        """Re-create the album with image bytes instead of URLs; drops images that fail to download."""
        if not self.http_client or self.http_client.is_closed:
            self.http_client = self._init_http_client()
        result = []
        for item in media_group:
            try:
                response = await self.http_client.get(
                    item.media, headers=_IMAGE_CHECK_HEADERS, follow_redirects=True,
                )
                response.raise_for_status()
            except Exception as e:
                logger.warning("[TelegramNewsBot] Cannot download image %s: %r", item.media, e)
                continue
            if len(response.content) > PHOTO_UPLOAD_LIMIT:
                logger.warning(
                    "[TelegramNewsBot] Image too big to upload (%d bytes): %s", len(response.content), item.media,
                )
                continue
            result.append(InputMediaPhoto(media=response.content))
        if result:
            first = media_group[0]
            result[0] = InputMediaPhoto(media=result[0].media, caption=first.caption, parse_mode=first.parse_mode)
        return result

    async def _send_albums(self, media_group: list[InputMediaPhoto]) -> Optional[SentMessage]:
        if len(media_group) > 10:
            return await self._send_large_media_group(media_group)
        result = await self.retry_handler.run_with_retry(
            self.bot.send_media_group,
            chat_id=self.channel_id,
            media=media_group,
        )
        message = _first_message(result)
        return SentMessage(message.message_id, is_caption=True) if message else None

    async def _prepare_media_group(
        self, text: str, images: list[str],
    ) -> list[InputMediaPhoto]:
        media_group = []
        caption_to_send, parse_mode = self._fit_html(text, CAPTION_LIMIT)

        valid_images_count = 0
        for i, image_url in enumerate(images):
            if valid_images_count >= self.config["max_images"]:
                break

            clean_url = self.formatter.clean_url(image_url)
            if not clean_url or (
                self.config["validate_images"]
                and not await self._validate_image_url(clean_url)
            ):
                logger.warning("Skipping invalid or unavailable image URL: %s", image_url)
                continue

            media_group.append(
                InputMediaPhoto(
                    media=clean_url,
                    caption=caption_to_send if valid_images_count == 0 else None,
                    parse_mode=parse_mode if valid_images_count == 0 else None,
                ),
            )
            valid_images_count += 1

        return media_group

    async def _send_large_media_group(self, media_group: list[InputMediaPhoto]) -> Optional[SentMessage]:
        """Send more than 10 photos as several albums; the caption sits on the first photo of the first album."""
        logger.info("Splitting large media group (%s items)", len(media_group))
        max_media_per_group = 10
        first: Optional[SentMessage] = None

        for i in range(0, len(media_group), max_media_per_group):
            group_slice = media_group[i : i + max_media_per_group]
            logger.info("Sending slice %s with %s items", i//max_media_per_group + 1, len(group_slice))
            result = await self.retry_handler.run_with_retry(
                self.bot.send_media_group,
                chat_id=self.channel_id,
                media=group_slice,
            )
            message = _first_message(result)
            if not message:
                return None
            if first is None:
                first = SentMessage(message.message_id, is_caption=True)

        return first

    @retry(max_retries=3, base_delay=1, backoff_factor=1.5)
    async def _validate_image_url(self, url: str) -> bool:
        """Validates if image URL is accessible."""
        try:
            if not self.http_client or self.http_client.is_closed:
                self.http_client = self._init_http_client()

            response = await self.http_client.head(url, headers=_IMAGE_CHECK_HEADERS, follow_redirects=True)
            if response.status_code in (403, 405):
                # Some CDNs reject HEAD requests — confirm with a real GET
                async with self.http_client.stream(
                    "GET", url, headers=_IMAGE_CHECK_HEADERS, follow_redirects=True,
                ) as streamed:
                    return streamed.status_code == 200
            return response.status_code == 200
        except Exception as e:
            logger.warning("Error validating image URL %s: %s", url, e)
            return False

