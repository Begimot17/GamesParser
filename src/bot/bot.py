import asyncio
import logging
import random
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote, urlparse

import httpx
import telegram
from telegram import InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError
from telegram.request import HTTPXRequest

from models.models import Post

logger = logging.getLogger(__name__)

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
    def __init__(
        self,
        token: str,
        channel_id: str,
        message_delay: int = DEFAULT_DELAYS["base_delay"],
        retry_delay: int = DEFAULT_DELAYS["base_delay"],
        max_retries: int = 5,
    ):
        # Clean the token by removing any comments or extra text
        self.token = token.split("#")[0].strip()
        if not self.token:
            raise ValueError("Invalid bot token provided")

        self.channel_id = channel_id
        self.message_delay = message_delay
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.max_message_length = 4000
        self.max_caption_length = 1024

        # Создаем HTTP-клиент с увеличенными таймаутами
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(**DEFAULT_TIMEOUTS),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            transport=httpx.AsyncHTTPTransport(retries=3),
        )

        # Инициализируем бота с нашим HTTP-клиентом
        self.bot = telegram.Bot(
            token=self.token,
            request=HTTPXRequest(
                connection_pool_size=10,
                read_timeout=DEFAULT_TIMEOUTS["read"],
                write_timeout=DEFAULT_TIMEOUTS["write"],
                connect_timeout=DEFAULT_TIMEOUTS["connect"],
                pool_timeout=DEFAULT_TIMEOUTS["pool"],
            ),
        )

        self.max_images = 5
        self._processed_ids = set()
        self._last_successful_request = datetime.now()
        self._connection_errors = 0
        self._max_connection_errors = 10
        self._connection_error_window = 300  # 5 минут
        self._rate_limit_errors = 0
        self._last_rate_limit = None
        self._rate_limit_window = 3600  # 1 час

    async def close(self):
        """Закрытие сессии бота."""
        if self.bot:
            self._processed_ids.clear()
            await self.bot.close()
        if self.http_client:
            await self.http_client.aclose()

    async def _check_connection(self) -> bool:
        """Проверка состояния соединения."""
        try:
            # Проверяем время с последнего успешного запроса
            time_since_last_success = (
                datetime.now() - self._last_successful_request
            ).total_seconds()

            # Если было много ошибок за короткое время, делаем паузу
            if (
                self._connection_errors >= self._max_connection_errors
                and time_since_last_success < self._connection_error_window
            ):
                wait_time = min(300, self._connection_errors * 30)  # Максимум 5 минут
                logger.warning(
                    f"Too many connection errors ({self._connection_errors}). Waiting {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
                self._connection_errors = 0
                return False

            # Проверяем соединение с Telegram API
            await self.bot.get_me()
            self._last_successful_request = datetime.now()
            self._connection_errors = 0
            return True

        except Exception as e:
            logger.error(f"Connection check failed: {str(e)}")
            self._connection_errors += 1
            return False

    async def _calculate_delay(
        self, attempt: int, is_rate_limit: bool = False
    ) -> float:
        """Расчет задержки с учетом всех факторов."""
        base_delay = self.retry_delay

        # Увеличиваем базовую задержку при превышении лимита
        if is_rate_limit:
            base_delay *= DEFAULT_DELAYS["rate_limit_multiplier"]
            self._rate_limit_errors += 1

        # Экспоненциальная задержка
        delay = base_delay * (DEFAULT_DELAYS["backoff_factor"] ** attempt)

        # Добавляем случайный джиттер
        jitter = random.uniform(
            -DEFAULT_DELAYS["jitter_range"], DEFAULT_DELAYS["jitter_range"]
        )
        delay += jitter

        # Ограничиваем задержку минимальным и максимальным значениями
        delay = max(
            DEFAULT_DELAYS["min_delay"], min(delay, DEFAULT_DELAYS["max_delay"])
        )

        return delay

    async def _check_rate_limit(self) -> bool:
        """Проверка состояния ограничений скорости."""
        if self._last_rate_limit:
            time_since_last_limit = (
                datetime.now() - self._last_rate_limit
            ).total_seconds()

            # Если было много ошибок за короткое время, увеличиваем задержку
            if (
                self._rate_limit_errors >= 3
                and time_since_last_limit < self._rate_limit_window
            ):
                wait_time = min(600, self._rate_limit_errors * 60)  # Максимум 10 минут
                logger.warning(
                    f"Too many rate limit errors ({self._rate_limit_errors}). Waiting {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
                return False

        return True

    async def _send_with_retry(self, method, *args, **kwargs):
        """Отправка сообщения с повторными попытками."""
        last_error = None
        base_delay = self.retry_delay

        for attempt in range(self.max_retries):
            try:
                # Проверяем ограничения скорости
                if not await self._check_rate_limit():
                    continue

                # Проверяем соединение перед каждой попыткой
                if not await self._check_connection():
                    delay = await self._calculate_delay(attempt)
                    await asyncio.sleep(delay)
                    continue

                result = await method(*args, **kwargs)
                if result:
                    self._last_successful_request = datetime.now()
                    self._rate_limit_errors = 0
                    return result
                logger.warning(
                    f"Method returned None, attempt {attempt + 1}/{self.max_retries}"
                )

            except RetryAfter as e:
                last_error = e
                self._last_rate_limit = datetime.now()
                wait_time = e.retry_after + 5  # Добавляем 5 секунд для надежности
                logger.warning(f"Rate limit hit, waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue

            except NetworkError as e:
                last_error = e
                self._connection_errors += 1
                if attempt == self.max_retries - 1:
                    raise

                delay = await self._calculate_delay(attempt)
                logger.warning(
                    f"Network error, attempt {attempt + 1}/{self.max_retries}: {str(e)}. Waiting {delay:.2f} seconds..."
                )
                await asyncio.sleep(delay)
                continue

            except TelegramError as e:
                logger.error(f"Telegram error: {str(e)}")
                raise

            except Exception as e:
                last_error = e
                self._connection_errors += 1
                if attempt == self.max_retries - 1:
                    raise

                delay = await self._calculate_delay(attempt)
                logger.warning(
                    f"Unexpected error, attempt {attempt + 1}/{self.max_retries}: {str(e)}. Waiting {delay:.2f} seconds..."
                )
                await asyncio.sleep(delay)
                continue

            # Если метод вернул None, ждем перед следующей попыткой
            delay = await self._calculate_delay(attempt)
            await asyncio.sleep(delay)

        if last_error:
            raise last_error
        return None

    def _split_text(self, text: str, max_length: int) -> List[str]:
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
        images: Optional[List[str]] = None,
    ) -> bool:
        """Отправка сообщения в канал."""
        try:
            if images:
                # Ограничиваем количество изображений
                images = images[: self.max_images]

                # Создаем медиагруппу
                media_group = []
                for i, image_url in enumerate(images):
                    # Очищаем URL
                    clean_url = self._clean_url(image_url)
                    if not clean_url:
                        logger.warning(f"Skipping invalid image URL: {image_url}")
                        continue

                    # Для первого изображения добавляем подпись
                    caption = text if i == 0 else None
                    media_group.append(
                        InputMediaPhoto(
                            media=clean_url, caption=caption, parse_mode=ParseMode.HTML
                        )
                    )

                if not media_group:
                    logger.warning("No valid images to send")
                    return False

                # Отправляем медиагруппу
                result = await self._send_with_retry(
                    self.bot.send_media_group,
                    chat_id=self.channel_id,
                    media=media_group,
                )
                return bool(
                    result
                )  # Возвращаем True только если сообщение успешно отправлено

            else:
                # Если нет изображений, отправляем только текст
                result = await self._send_with_retry(
                    self.bot.send_message,
                    chat_id=self.channel_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
                return bool(
                    result
                )  # Возвращаем True только если сообщение успешно отправлено

        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
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
        """Очистка текста от всех отступов и форматирования"""
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
        """Форматирование даты в формат DD.MM.YYYY"""
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
        """Форматирование ссылки на магазин"""
        store_name = self._clean_text(store_name)
        if store_name.lower() == "steam":
            return f"🎮 Steam: {store_url}"
        elif store_name.lower() == "epic games":
            return f"🎮 Epic: {store_url}"
        elif store_name.lower() == "gog":
            return f"🎮 GOG: {store_url}"
        return f"🎮 {store_name}: {store_url}"

    def _safe_unquote(self, text: str) -> str:
        """Безопасное декодирование URL-encoded строки"""
        try:
            if "%" in text:
                return unquote(text)
            return text
        except Exception as e:
            logger.warning(f"Error decoding text: {e}")
            return text

    def _clean_url(self, url: str) -> str:
        """Очистка URL от реферальных параметров и валидация"""
        if not url:
            return ""

        # Parse the URL
        parsed = urlparse(url)

        # Remove any query parameters
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Ensure the URL is valid
        if not parsed.scheme or not parsed.netloc:
            logger.warning(f"Invalid URL format: {url}")
            return ""

        # Ensure the URL uses HTTPS
        if parsed.scheme != "https":
            clean_url = clean_url.replace("http://", "https://")

        return clean_url

    def _format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки"""
        try:
            # Форматируем заголовок с ссылкой
            title_link = f'<a href="{post.link}">{post.title}</a>'

            # Ищем ссылки на магазины в тексте
            store_links = []
            for store, url in post.metadata.store_links.items():
                # Очищаем URL от реферальных параметров
                clean_url = self._clean_url(url)
                store_links.append(f'<a href="{clean_url}">{store}</a>')

            # Ищем ссылки на магазины в тексте
            text = post.content
            store_patterns = {
                "Steam": r"https?://(?:store\.)?steampowered\.com/\S+",
                "Epic Games": r"https?://(?:store\.)?epicgames\.com/\S+",
                "GOG": r"https?://(?:store\.)?gog\.com/\S+",
                "itch.io": r"https?://(?:store\.)?itch\.io/\S+",
            }

            # Ищем ссылки в HTML-тексте
            html_pattern = r'<a[^>]+(?:href|title)="([^"]+)"[^>]*>'
            matches = re.findall(html_pattern, text)
            for url in matches:
                clean_url = self._clean_url(url)
                if any(
                    store in clean_url.lower()
                    for store in [
                        "steampowered.com",
                        "epicgames.com",
                        "gog.com",
                        "itch.io",
                    ]
                ):
                    store_name = (
                        "Steam"
                        if "steampowered.com" in clean_url.lower()
                        else "Epic Games"
                        if "epicgames.com" in clean_url.lower()
                        else "GOG"
                        if "gog.com" in clean_url.lower()
                        else "itch.io"
                    )
                    if clean_url not in [
                        url for _, url in post.metadata.store_links.items()
                    ]:
                        store_links.append(f'<a href="{clean_url}">{store_name}</a>')
                        # Удаляем ссылку из текста
                        text = re.sub(
                            f'<a[^>]+(?:href|title)="{re.escape(url)}"[^>]*>.*?</a>',
                            "",
                            text,
                        )

            # Ищем упоминания магазинов в тексте
            store_mentions = {
                "Epic Games": r"Epic\s+Games",
                "Steam": r"Steam",
                "GOG": r"GOG",
                "itch.io": r"itch\.io",
            }

            for store_name, pattern in store_mentions.items():
                if re.search(pattern, text, re.IGNORECASE):
                    # Если магазин упомянут, но ссылки нет, добавляем ссылку на главную страницу магазина
                    store_url = {
                        "Epic Games": "https://store.epicgames.com",
                        "Steam": "https://store.steampowered.com",
                        "GOG": "https://www.gog.com",
                        "itch.io": "https://itch.io",
                    }[store_name]
                    if store_url not in [
                        url for _, url in post.metadata.store_links.items()
                    ]:
                        store_links.append(f'<a href="{store_url}">{store_name}</a>')

            for store_name, pattern in store_patterns.items():
                matches = re.findall(pattern, text)
                for url in matches:
                    clean_url = self._clean_url(url)
                    if clean_url not in [
                        url for _, url in post.metadata.store_links.items()
                    ]:
                        store_links.append(f'<a href="{clean_url}">{store_name}</a>')
                        # Удаляем ссылку из текста
                        text = re.sub(pattern, "", text)

            stores_text = (
                " | ".join(store_links) if store_links else "Нет ссылок на магазины"
            )

            # Форматируем метаданные
            metadata = []
            if post.metadata and post.metadata.date:
                formatted_date = post.metadata.date.strftime("%d.%m.%Y %H:%M")
                metadata.append(f"📅 {formatted_date}")

            # Форматируем рейтинг
            rating_text = (
                f"⭐ {post.metadata.rating}"
                if post.metadata and post.metadata.rating
                else ""
            )

            # Обрезаем только поле text до 200 символов
            text = text[:500] + "..." if len(text) > 500 else text

            # Собираем все части сообщения
            message_parts = [
                f"🎮 {title_link}",
                f"📊 {rating_text}",
                f"🛒 {stores_text}",
                *metadata,
                "",
                text,
            ]

            return "\n".join(message_parts)

        except Exception as e:
            logger.error(f"Error formatting message: {str(e)}")
            return f"Error formatting message: {str(e)}"

    async def send_new_posts(self, new_posts: List[Post]) -> List[int]:
        """Отправка новых постов в канал"""
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
                    images=post.images[: self.max_images] if post.images else None,
                )

                if success:
                    # Помечаем пост как отправленный только при успешной отправке
                    self._processed_ids.add(post.id)
                    sent_post_ids.append(post.id)
                    logger.info(f"Successfully sent post {post.id}")

                    # Увеличиваем задержку между постами
                    delay = await self._calculate_delay(0, self._rate_limit_errors > 0)
                    await asyncio.sleep(delay)
                else:
                    # Если отправка не удалась, не помечаем пост как отправленный
                    logger.error(f"Failed to send post {post.id}")
                    # Очищаем _processed_ids для этого поста, чтобы можно было попробовать снова
                    self._processed_ids.discard(post.id)
                    # Увеличиваем задержку при ошибке
                    delay = await self._calculate_delay(1, True)
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing post {post.id}: {str(e)}")
                # При ошибке также очищаем _processed_ids для этого поста
                self._processed_ids.discard(post.id)
                # Увеличиваем задержку при ошибке
                delay = await self._calculate_delay(1, True)
                await asyncio.sleep(delay)

        return sent_post_ids
