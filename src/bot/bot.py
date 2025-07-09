"""Telegram bot logic for GamesParser project."""

import asyncio
import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx
from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode

from common import logger
from src.bot.message_formatter import MessageFormatter
from src.bot.retry_handler import RetryHandler
from src.models.models import Post


# Настройки таймаутов для HTTP-запросов
DEFAULT_TIMEOUTS = {
    "connect": 30.0,  # Таймаут на установку соединения
    "read": 60.0,  # Таймаут на чтение данных
    "write": 30.0,  # Таймаут на запись данных
    "pool": 30.0,  # Таймаут на получение соединения из пула
}

# Настройки задержек и ограничений
DEFAULT_DELAYS = {
    "base_delay": 30,  # Базовая задержка между запросами
    "min_delay": 20,  # Минимальная задержка
    "max_delay": 300,  # Максимальная задержка
    "rate_limit_multiplier": 2,  # Множитель при превышении лимита
    "backoff_factor": 2,  # Фактор экспоненциального роста
    "jitter_range": 5,  # Разброс случайной задержки
}


class TelegramNewsBot:
    """Telegram bot for sending news posts to a channel."""

    DEFAULTS = {
        "message_delay": DEFAULT_DELAYS["base_delay"],
        "retry_delay": DEFAULT_DELAYS["base_delay"],
        "max_retries": 5,
        "max_images": 10,
    }

    def __init__(self, token: str, channel_id: str, config: dict = None):
        logger.info(f"[TelegramNewsBot] Initializing bot for channel {channel_id}")
        # Clean the token by removing any comments or extra text
        self.token = token.split("#")[0].strip()
        if not self.token:
            logger.error("[TelegramNewsBot] Invalid bot token provided")
            raise ValueError("Invalid bot token provided")

        self.channel_id = channel_id
        self.config = {**self.DEFAULTS, **(config or {})}
        self.max_message_length = 4000
        self.max_caption_length = 1024

        # Создаем HTTP-клиент с увеличенными таймаутами
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(**DEFAULT_TIMEOUTS),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            transport=httpx.AsyncHTTPTransport(retries=3),
        )
        self.bot = Bot(token=self.token)
        self._processed_ids = set()
        self._last_successful_request = datetime.now()
        self._connection_errors = 0
        self._max_connection_errors = 10
        self._connection_error_window = 300  # 5 минут
        self._rate_limit_errors = 0
        self._last_rate_limit = None
        self._rate_limit_window = 3600  # 1 час
        self.formatter = MessageFormatter()
        self.retry_handler = RetryHandler(
            config={
                "max_retries": self.config["max_retries"],
                "base_delay": self.config["retry_delay"],
            },
        )
        logger.info(f"[TelegramNewsBot] Bot initialized successfully for channel {channel_id}")

    async def close(self):
        """Закрытие сессии бота."""
        logger.info("[TelegramNewsBot] Closing bot session...")
        if self.http_client:
            await self.http_client.aclose()
        logger.info("[TelegramNewsBot] Bot session closed.")

    async def _check_connection(self) -> bool:
        """Проверка состояния соединения."""
        try:
            # Проверяем время с последнего успешного запроса
            time_since_last_success = (datetime.now() - self._last_successful_request).total_seconds()

            # Если было много ошибок за короткое время, делаем паузу
            if (
                self._connection_errors >= self._max_connection_errors
                and time_since_last_success < self._connection_error_window
            ):
                wait_time = min(300, self._connection_errors * 30)  # Максимум 5 минут
                logger.warning(
                    "Too many connection errors (%d). Waiting %d seconds...",
                    self._connection_errors,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
                self._connection_errors = 0
                return False

            # Проверяем соединение с Telegram API
            self._last_successful_request = datetime.now()
            self._connection_errors = 0
            return True

        except Exception as e:
            logger.error(f"Connection check failed: {str(e)}")
            self._connection_errors += 1
            return False

    async def _calculate_delay(self, attempt: int, *, is_rate_limit: bool = False) -> float:
        """Расчет задержки с учетом всех факторов."""
        base_delay = self.config["retry_delay"]

        # Увеличиваем базовую задержку при превышении лимита
        if is_rate_limit:
            base_delay *= DEFAULT_DELAYS["rate_limit_multiplier"]
            self._rate_limit_errors += 1

        # Экспоненциальная задержка
        delay = base_delay * (DEFAULT_DELAYS["backoff_factor"] ** attempt)

        # Добавляем случайный джиттер
        jitter = random.uniform(-DEFAULT_DELAYS["jitter_range"], DEFAULT_DELAYS["jitter_range"])  # noqa: S311
        delay += jitter

        # Ограничиваем задержку минимальным и максимальным значениями
        delay = max(DEFAULT_DELAYS["min_delay"], min(delay, DEFAULT_DELAYS["max_delay"]))

        return delay

    async def _check_rate_limit(self) -> bool:
        """Проверка состояния ограничений скорости."""
        if self._last_rate_limit:
            time_since_last_limit = (datetime.now() - self._last_rate_limit).total_seconds()

            # Если было много ошибок за короткое время, увеличиваем задержку
            if self._rate_limit_errors >= 3 and time_since_last_limit < self._rate_limit_window:
                wait_time = min(600, self._rate_limit_errors * 60)  # Максимум 10 минут
                logger.warning(
                    "Too many rate limit errors (%d). Waiting %d seconds...",
                    self._rate_limit_errors,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
                return False

        return True

    async def _send_with_retry(self, method, *args, **kwargs):
        """Отправка сообщения с повторными попытками (делегируется RetryHandler)"""
        return await self.retry_handler.run_with_retry(method, *args, **kwargs)

    def _split_text(self, text: str, max_length: int) -> list[str]:
        """Разделение текста на части, не превышающие максимальную длину."""
        if len(text) <= max_length:
            return [text]

        parts = []
        current_part = ""
        for line in text.split("\n"):
            if len(current_part) + len(line) + 1 > max_length:
                if current_part:
                    parts.append(current_part.strip())
                current_part = line
            else:
                if current_part:
                    current_part += "\n"
                current_part += line

        if current_part:
            parts.append(current_part.strip())

        return parts

    async def send_message(
        self,
        text: str,
        images: Optional[list[str]] = None,
    ) -> bool:
        logger.info(
            f"TelegramNewsBot Sending message to channel {self.channel_id}. Images: {len(images) if images else 0}",
        )
        try:
            if images:
                images = images[: self.config["max_images"]]
                media_group = []
                for i, image_url in enumerate(images):
                    clean_url = self.formatter.clean_url(image_url)
                    if not clean_url:
                        logger.warning(f"TelegramNewsBot Skipping invalid image URL: {image_url}")
                        continue
                    caption = text if i == 0 else None
                    media_group.append(InputMediaPhoto(media=clean_url, caption=caption, parse_mode=ParseMode.HTML))
                if not media_group:
                    logger.warning("TelegramNewsBot No valid images to send")
                    return False
                # Асинхронная отправка медиагруппы
                result = await self.bot.send_media_group(chat_id=self.channel_id, media=media_group)
                return bool(result)
            # Если нет изображений, отправляем только текст
            result = await self.bot.send_message(chat_id=self.channel_id, text=text, parse_mode=ParseMode.HTML)
            return bool(result)
        except Exception as e:
            logger.error(f"TelegramNewsBot Error sending message: {e}", exc_info=True)
            return False

    def _is_valid_url(self, url: str) -> bool:
        """Проверяет валидность URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception as e:
            logger.error(f"Error validating URL {url}: {e}")
            return False

    def _clean_text(self, text: str) -> str:
        """Очистка текста от всех отступов и форматирования."""
        if not text:
            return ""
        # Убираем все пробельные символы в начале и конце
        text = text.strip()
        # Заменяем все последовательности пробельных символов на один пробел
        text = re.sub(r"\s+", " ", text)
        # Заменяем множественные переносы строк на один пробел
        text = re.sub(r"\n+", " ", text)
        # Убираем множественные точки
        text = re.sub(r"\.{3,}", "...", text)
        # Удаляем ссылки на магазины
        text = re.sub(r"https?://(?:store\.)?steampowered\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?epicgames\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?gog\.com/\S+", "", text)
        text = re.sub(r"https?://(?:store\.)?itch\.io/\S+", "", text)
        return text

    def _format_date(self, date_str: str) -> str:
        """Форматирование даты в формат DD.MM.YYYY."""
        try:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                try:
                    date = datetime.strptime(date_str, fmt)
                    return date.strftime("%d.%m.%Y")
                except ValueError:
                    continue
            return date_str
        except Exception as e:
            logger.warning(f"Error formatting date {date_str}: {e}")
            return date_str

    def _format_store_link(self, store_name: str, store_url: str) -> str:
        """Форматирование ссылки на магазин."""
        store_name = self._clean_text(store_name)
        if store_name.lower() == "steam":
            return f"🎮 Steam: {store_url}"
        if store_name.lower() == "epic games":
            return f"🎮 Epic: {store_url}"
        if store_name.lower() == "gog":
            return f"🎮 GOG: {store_url}"
        return f"🎮 {store_name}: {store_url}"

    def _safe_unquote(self, text: str) -> str:
        """Безопасное декодирование URL-encoded строки."""
        try:
            if "%" in text:
                return unquote(text)
            return text
        except Exception as e:
            logger.warning(f"Error decoding text: {e}")
            return text

    def _format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки (делегируется MessageFormatter)."""
        return self.formatter.format_message(post)

    async def send_new_posts(self, new_posts: list[Post]) -> list[int]:
        """Отправка новых постов в канал."""
        sent_post_ids = []
        for post in new_posts:
            try:
                # Пропускаем посты без изображений
                if not post.images:
                    logger.info(f"Skipping post {post.id} - no images found")
                    continue

                # Проверяем, не был ли пост уже отправлен
                if post.id in self._processed_ids:
                    logger.info(f"Post {post.id} was already sent, skipping...")
                    continue

                # Форматируем сообщение
                message = self._format_message(post)

                # Отправляем сообщение
                success = await self.send_message(
                    text=message,
                    images=post.images[: self.config["max_images"]] if post.images else None,
                )

                if success:
                    # Помечаем пост как отправленный только при успешной отправке
                    self._processed_ids.add(post.id)
                    sent_post_ids.append(post.id)
                    logger.info(f"Successfully sent post {post.id}")

                    # Увеличиваем задержку между постами
                    delay = await self._calculate_delay(0, is_rate_limit=self._rate_limit_errors > 0)
                    await asyncio.sleep(delay)
                else:
                    # Если отправка не удалась, не помечаем пост как отправленный
                    logger.error(f"Failed to send post {post.id}")
                    # Очищаем _processed_ids для этого поста, чтобы можно было попробовать снова
                    self._processed_ids.discard(post.id)
                    # Увеличиваем задержку при ошибке
                    delay = await self._calculate_delay(1, is_rate_limit=True)
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing post {post.id}: {str(e)}", exc_info=True)
                # При ошибке также очищаем _processed_ids для этого поста
                self._processed_ids.discard(post.id)
                # Увеличиваем задержку при ошибке
                delay = await self._calculate_delay(1, is_rate_limit=True)
                await asyncio.sleep(delay)

        return sent_post_ids
