"""Telegram bot logic for GamesParser project."""

from typing import Optional
import httpx
from telegram import Bot, InputMediaPhoto, request
from telegram.constants import ParseMode

from src.common.logger import logger
from src.models.models import Post
from src.bot.retry_handler import RetryHandler, retry
from src.bot.message_formatter import MessageFormatter


class TelegramNewsBot:
    """Telegram bot for posting news updates."""

    def __init__(self, token: str, channel_id: str, config: Optional[dict] = None):
        logger.info(f"[TelegramNewsBot] Initializing bot for channel {channel_id}")
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
            pool_timeout=30.0
        )
        self.bot = Bot(token=self.token, request=request_instance)
        
        self.http_client = self._init_http_client()
        self.retry_handler = self._init_retry_handler()
        self.formatter = MessageFormatter()

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

    async def close(self):
        logger.info("[TelegramNewsBot] Closing bot session...")
        if self.http_client:
            await self.http_client.aclose()
        logger.info("[TelegramNewsBot] Bot session closed.")

    async def send_message(self, text: str, images: Optional[list[str]] = None) -> bool:
        """Sends a message to the channel, choosing the appropriate method."""
        if images:
            success = await self._send_media_group_message(text, images)
        else:
            success = await self._send_text_message(text)
        return success

    async def _send_text_message(self, text: str) -> bool:
        message_content = text
        
        if len(message_content) > 4096:
            logger.warning(
                f"[TelegramNewsBot] Text message too long ({len(message_content)}), converting to plain text"
            )
            message_content = self.formatter.to_plain_text(message_content)[:4096]
            # parse_mode logic removed as we fallback to simple text, but assuming HTML is preferred unless forced plain
            # Actually, to_plain_text implies we strip html.
            
        logger.info(
            f"[TelegramNewsBot] Sending text message (first 500 chars): {message_content[:500]}"
        )
        # Use retry handler configured in init
        result = await self.retry_handler.run_with_retry(
            self.bot.send_message,
            chat_id=self.channel_id,
            text=message_content,
            parse_mode=ParseMode.HTML if "<" in message_content else None
        )
        return bool(result)

    async def _send_media_group_message(self, text: str, images: list[str]) -> bool:
        """Sends a media group with caption."""
        media_group = await self._prepare_media_group(text, images)
        if not media_group:
            logger.warning("[TelegramNewsBot] No valid media to send, falling back to text message")
            return await self._send_text_message(text)

        if len(media_group) > 10:
             return await self._send_large_media_group(media_group)

        logger.info(
            f"[TelegramNewsBot] Sending media group with caption: {media_group[0].caption[:500] if media_group[0].caption else 'No caption'}"
        )
        
        result = await self.retry_handler.run_with_retry(
            self.bot.send_media_group,
            chat_id=self.channel_id,
            media=media_group,
        )
        return bool(result)

    async def _prepare_media_group(
        self, text: str, images: list[str]
    ) -> list[InputMediaPhoto]:
        media_group = []
        caption_html = text
        caption_plain = self.formatter.to_plain_text(caption_html)
        caption_to_send = caption_html
        parse_mode = ParseMode.HTML

        if len(caption_html) > 1024:
            logger.warning(
                f"[TelegramNewsBot] Media caption too long ({len(caption_html)}), converting to plain text"
            )
            caption_to_send = (
                caption_plain[:1021] + "..."
                if len(caption_plain) > 1024
                else caption_plain
            )
            parse_mode = None

        valid_images_count = 0
        for i, image_url in enumerate(images):
            if valid_images_count >= self.config["max_images"]:
                break
                
            clean_url = self.formatter.clean_url(image_url)
            if not clean_url or (
                self.config["validate_images"]
                and not await self._validate_image_url(clean_url)
            ):
                logger.warning(f"Skipping invalid or unavailable image URL: {image_url}")
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

    async def _send_large_media_group(self, media_group: list[InputMediaPhoto]) -> bool:
        logger.info(f"Splitting large media group ({len(media_group)} items)")
        max_media_per_group = 10
        success = True
        
        for i in range(0, len(media_group), max_media_per_group):
            group_slice = media_group[i : i + max_media_per_group]
            
            # Helper logic: only first item of first group has caption?
            # Or if logical split (e.g. 20 images = 2 posts), maybe repeat caption or add numbering?
            # Current implementation logic: only first item of FIRST group has caption (already set in _prepare).
            # But subsequent groups shouldn't have caption set on their first item if it was meant for the whole post, 
            # OR they should just be images without caption.
            # _prepare_media_group sets caption on item 0.
            # If item 0 is in first slice, subsequent slices won't have caption.
            
            logger.info(f"Sending slice {i//max_media_per_group + 1} with {len(group_slice)} items")
            result = await self.retry_handler.run_with_retry(
                self.bot.send_media_group,
                chat_id=self.channel_id,
                media=group_slice,
            )
            if not result:
                success = False
        
        return success

    @retry(max_retries=3, base_delay=1, backoff_factor=1.5)
    async def _validate_image_url(self, url: str) -> bool:
        """Validates if image URL is accessible."""
        try:
            if not self.http_client or self.http_client.is_closed:
                self.http_client = self._init_http_client()
                
            response = await self.http_client.head(url)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Error validating image URL {url}: {e}")
            return False

    def _format_message(self, post: Post) -> str:
        return self.formatter.format_message(post)
