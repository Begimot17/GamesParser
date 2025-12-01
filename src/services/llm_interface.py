from abc import ABC, abstractmethod
from typing import Any, Dict


class LLMInterface(ABC):
    @abstractmethod
    async def generate_response(self, prompt: str, history: list[dict], **kwargs) -> str:
        """
        Сгенерировать ответ на основе system_prompt и истории сообщений.
        :param prompt: system_prompt или пользовательский prompt
        :param history: история сообщений (список словарей с role/content)
        :param kwargs: дополнительные параметры
        :return: сгенерированный ответ
        """

    @abstractmethod
    async def generate_reminder_message(self, reminder_type: str, user_context: Dict[str, Any]) -> str:
        """
        Сгенерировать текст напоминания по типу и контексту пользователя.
        :param reminder_type: тип напоминания (например, 'тренировка')
        :param user_context: словарь с данными пользователя
        :return: текст напоминания
        """

    @abstractmethod
    async def generate_updated_prompt(self, prompt: str, history: list[dict], **kwargs) -> str:
        """
        Сгенерировать обновлённый prompt на основе текущего prompt и истории сообщений.
        :param prompt: текущий prompt
        :param history: история сообщений (список словарей с role/content)
        :param kwargs: дополнительные параметры
        :return: обновлённый prompt
        """

    @abstractmethod
    async def extract_article_info(self, page_text: str, url: str) -> dict:
        """
        Извлечь структурированную информацию из текста статьи.
        :param page_text: полный текст страницы статьи
        :param url: URL статьи
        :return: словарь с извлеченной информацией (заголовок, описание, ссылки на магазины и т.д.)
        """
