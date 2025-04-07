import asyncio
import logging
import re
from datetime import datetime
from typing import List, Optional, Union
from urllib.parse import unquote, urlparse, parse_qsl

import telegram
from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, NetworkError
from telegram.request import HTTPXRequest

from models.models import Post
from config.config import Config

logger = logging.getLogger(__name__)


class TelegramNewsBot:
    def __init__(
        self,
        token: str,
        channel_id: str,
        message_delay: int = 10,
        retry_delay: int = 5,
        max_retries: int = 3,
    ):
        # Clean the token by removing any comments or extra text
        self.token = token.split('#')[0].strip()
        if not self.token:
            raise ValueError("Invalid bot token provided")
            
        self.channel_id = channel_id
        self.message_delay = message_delay
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.max_message_length = 4000
        self.max_caption_length = 1024
        self.bot = telegram.Bot(token=self.token, request=HTTPXRequest())
        self.max_images = 5
        self._processed_ids = set()

    async def close(self):
        """Закрытие сессии бота."""
        if self.bot:
            self._processed_ids.clear()  # Очищаем множество отправленных постов
            await self.bot.close()

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

    async def _send_with_retry(self, method, *args, **kwargs):
        """Отправка сообщения с повторными попытками."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                result = await method(*args, **kwargs)
                # Если сообщение успешно отправлено, возвращаем результат
                if result:
                    return result
                # Если результат None, пробуем еще раз
                logger.warning(f"Method returned None, attempt {attempt + 1}/{self.max_retries}")
                await asyncio.sleep(self.retry_delay * (attempt + 1))
            except RetryAfter as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    raise
                wait_time = e.retry_after
                logger.warning(f"Rate limit hit, waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            except NetworkError as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"Network error, attempt {attempt + 1}/{self.max_retries}: {str(e)}")
                await asyncio.sleep(self.retry_delay * (attempt + 1))
            except TelegramError as e:
                logger.error(f"Telegram error: {str(e)}")
                raise

        # Если все попытки исчерпаны, выбрасываем последнюю ошибку
        if last_error:
            raise last_error
        return None

    async def send_message(
        self,
        text: str,
        images: Optional[List[str]] = None,
    ) -> bool:
        """Отправка сообщения в канал."""
        try:
            if images:
                # Ограничиваем количество изображений
                images = images[:self.max_images]
                
                # Создаем медиагруппу
                media_group = []
                for i, image_url in enumerate(images):
                    # Для первого изображения добавляем подпись
                    caption = text if i == 0 else None
                    media_group.append(
                        InputMediaPhoto(
                            media=image_url,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    )

                # Отправляем медиагруппу
                result = await self._send_with_retry(
                    self.bot.send_media_group,
                    chat_id=self.channel_id,
                    media=media_group
                )
                return bool(result)  # Возвращаем True только если сообщение успешно отправлено

            else:
                # Если нет изображений, отправляем только текст
                result = await self._send_with_retry(
                    self.bot.send_message,
                    chat_id=self.channel_id,
                    text=text,
                    parse_mode=ParseMode.HTML
                )
                return bool(result)  # Возвращаем True только если сообщение успешно отправлено

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
        text = re.sub(r'https?://(?:store\.)?steampowered\.com/\S+', '', text)
        text = re.sub(r'https?://(?:store\.)?epicgames\.com/\S+', '', text)
        text = re.sub(r'https?://(?:store\.)?gog\.com/\S+', '', text)
        text = re.sub(r'https?://(?:store\.)?itch\.io/\S+', '', text)
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
        """Очистка URL от реферальных параметров"""
        try:
            # Если это HTML-ссылка, извлекаем URL из атрибута href или title
            if '<a' in url:
                # Ищем URL в атрибуте href
                href_match = re.search(r'href="([^"]+)"', url)
                if href_match:
                    url = href_match.group(1)
                # Ищем URL в атрибуте title
                title_match = re.search(r'title="([^"]+)"', url)
                if title_match:
                    url = title_match.group(1)

            parsed = urlparse(url)
            
            # Если это URL Пикабу, пытаемся извлечь прямую ссылку на магазин
            if "pikabu.ru" in parsed.netloc:
                # Ищем параметр 'u' или 't' в URL, который содержит прямую ссылку
                query_params = dict(parse_qsl(parsed.query))
                direct_url = query_params.get('u') or query_params.get('t')
                if direct_url:
                    # Декодируем URL
                    direct_url = unquote(direct_url)
                    # Проверяем, что это действительно ссылка на магазин
                    if any(store in direct_url.lower() for store in ['steampowered.com', 'epicgames.com', 'gog.com', 'itch.io']):
                        return direct_url
            
            # Если это не URL Пикабу или не удалось извлечь прямую ссылку,
            # проверяем, является ли URL ссылкой на магазин
            if any(store in url.lower() for store in ['steampowered.com', 'epicgames.com', 'gog.com', 'itch.io']):
                # Очищаем URL от параметров
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            # Если это не ссылка на магазин, возвращаем исходный URL
            return url
            
        except Exception as e:
            logger.warning(f"Error cleaning URL {url}: {e}")
            return url

    def _format_message(self, post: Post) -> str:
        """Форматирование сообщения для отправки"""
        try:
            # Форматируем заголовок с ссылкой
            title_link = f'<a href="{post.link}">{post.title}</a>'

            # Ищем ссылки на магазины в тексте
            store_links = []
            for store, url in post.stores.items():
                # Очищаем URL от реферальных параметров
                clean_url = self._clean_url(url)
                store_links.append(f'<a href="{clean_url}">{store}</a>')

            # Ищем ссылки на магазины в тексте
            text = post.text
            store_patterns = {
                'Steam': r'https?://(?:store\.)?steampowered\.com/\S+',
                'Epic Games': r'https?://(?:store\.)?epicgames\.com/\S+',
                'GOG': r'https?://(?:store\.)?gog\.com/\S+',
                'itch.io': r'https?://(?:store\.)?itch\.io/\S+'
            }

            # Ищем ссылки в HTML-тексте
            html_pattern = r'<a[^>]+(?:href|title)="([^"]+)"[^>]*>'
            matches = re.findall(html_pattern, text)
            for url in matches:
                clean_url = self._clean_url(url)
                if any(store in clean_url.lower() for store in ['steampowered.com', 'epicgames.com', 'gog.com', 'itch.io']):
                    store_name = 'Steam' if 'steampowered.com' in clean_url.lower() else \
                               'Epic Games' if 'epicgames.com' in clean_url.lower() else \
                               'GOG' if 'gog.com' in clean_url.lower() else \
                               'itch.io'
                    if clean_url not in [url for _, url in post.stores.items()]:
                        store_links.append(f'<a href="{clean_url}">{store_name}</a>')
                        # Удаляем ссылку из текста
                        text = re.sub(f'<a[^>]+(?:href|title)="{re.escape(url)}"[^>]*>.*?</a>', '', text)

            # Ищем упоминания магазинов в тексте
            store_mentions = {
                'Epic Games': r'Epic\s+Games',
                'Steam': r'Steam',
                'GOG': r'GOG',
                'itch.io': r'itch\.io'
            }

            for store_name, pattern in store_mentions.items():
                if re.search(pattern, text, re.IGNORECASE):
                    # Если магазин упомянут, но ссылки нет, добавляем ссылку на главную страницу магазина
                    store_url = {
                        'Epic Games': 'https://store.epicgames.com',
                        'Steam': 'https://store.steampowered.com',
                        'GOG': 'https://www.gog.com',
                        'itch.io': 'https://itch.io'
                    }[store_name]
                    if store_url not in [url for _, url in post.stores.items()]:
                        store_links.append(f'<a href="{store_url}">{store_name}</a>')

            for store_name, pattern in store_patterns.items():
                matches = re.findall(pattern, text)
                for url in matches:
                    clean_url = self._clean_url(url)
                    if clean_url not in [url for _, url in post.stores.items()]:
                        store_links.append(f'<a href="{clean_url}">{store_name}</a>')
                        # Удаляем ссылку из текста
                        text = re.sub(pattern, '', text)

            stores_text = (
                " | ".join(store_links) if store_links else "Нет ссылок на магазины"
            )

            # Форматируем метаданные
            metadata = []
            if post.metadata.date:
                metadata.append(f"📅 {post.metadata.date}")
            if post.metadata.tags:
                tags_text = " ".join([f"#{tag}" for tag in post.metadata.tags])
                metadata.append(f"🏷️ {tags_text}")

            # Форматируем рейтинг
            rating_text = f"⭐ {post.rating}" if post.rating else ""

            # Обрезаем только поле text до 200 символов
            text = text[:500] + "..." if len(text) > 500 else text

            # Собираем все части сообщения
            message_parts = [
                f"🎮 {title_link}",
                f"📊 {rating_text}",
                f"🛒 {stores_text}",
                *metadata,
                "",
                text
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
                    images=post.images[:self.max_images] if post.images else None
                )

                if success:
                    # Помечаем пост как отправленный только при успешной отправке
                    self._processed_ids.add(post.id)
                    sent_post_ids.append(post.id)
                    logger.info(f"Successfully sent post {post.id}")
                    # Ждем перед следующей попыткой
                    await asyncio.sleep(self.retry_delay)
                else:
                    # Если отправка не удалась, не помечаем пост как отправленный
                    logger.error(f"Failed to send post {post.id}")
                    # Очищаем _processed_ids для этого поста, чтобы можно было попробовать снова
                    self._processed_ids.discard(post.id)
                    # Ждем перед следующей попыткой
                    await asyncio.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"Error processing post {post.id}: {str(e)}")
                # При ошибке также очищаем _processed_ids для этого поста
                self._processed_ids.discard(post.id)
                # Ждем перед следующей попыткой
                await asyncio.sleep(self.retry_delay)

        return sent_post_ids 