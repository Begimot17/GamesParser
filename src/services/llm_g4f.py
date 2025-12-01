import json
import re
from typing import Any, Dict

from g4f.client import AsyncClient

from src.common import logger
from src.config.config import Config
from src.services.llm_interface import LLMInterface


class LLMG4F(LLMInterface):
    def __init__(self):
        self.client = AsyncClient()
        self.model = Config.LLM_MODEL

    async def generate_response(self, prompt: str, history: list[dict], **kwargs) -> str:
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.insert(0, {"role": "system", "content": prompt})

        logger.info(f"Sending request to LLM with model {self.model}")
        response = await self.client.chat.completions.create(model=self.model, messages=messages, web_search=False)
        response_text = response.choices[0].message.content
        logger.info(f"LLM response: {response_text[:200]}...")
        return response_text

    async def extract_article_info(self, page_text: str, url: str) -> dict:
        """Извлечь структурированную информацию из текста статьи."""
        prompt = """Ты — эксперт по анализу игровых новостей. Твоя задача — извлечь структурированную информацию из текста статьи и вернуть ТОЛЬКО валидный JSON.

Формат JSON:
{
  "title": "Точный и полный заголовок статьи",
  "summary": "Краткое описание новости (2-3 предложения, самое главное)",
  "content": "Основной текст статьи, очищенный от рекламы, навигации и другого мусора. Сохрани абзацы.",
  "rating": null,
  "store_links": {
    "Steam": "полная_ссылка_если_найдена",
    "Epic Games": "полная_ссылка_если_найдена",
    "GOG": "полная_ссылка_если_найдена"
  },
  "game_title": "Название игры, если упоминается",
  "genre": "Жанр игры, если упоминается",
  "release_date": "Дата выхода, если упоминается",
  "platforms": ["Список платформ, если упоминаются"],
  "price": "Цена, если упоминается",
  "discount": "Размер скидки, если упоминается",
  "tags": ["Список релевантных тегов"]
}

КРИТИЧЕСКИ ВАЖНО:
- Возвращай ТОЛЬКО JSON, без каких-либо других слов и комментариев.
- В `store_links` включай ТОЛЬКО магазины с реальными, полными ссылками.
- Если какой-то информации нет, используй `null` или пустой список `[]`.
- Игнорируй комментарии, рекламу и навигационные элементы.

Текст статьи для анализа:"""

        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": page_text[:8000]}]

        try:
            logger.info(f"Extracting article info from {url} using {self.model}")
            response = await self.client.chat.completions.create(model=self.model, messages=messages, web_search=False)
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"LLM raw response for {url}: {response_text}")

            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                logger.warning(f"No JSON found in LLM response for {url}")
                return self._default_error_response("No JSON found in response")

            json_str = json_match.group()
            data = json.loads(json_str)

            if "store_links" in data and isinstance(data["store_links"], dict):
                data["store_links"] = {k: v for k, v in data["store_links"].items() if v and "http" in str(v)}

            logger.info(f"Successfully extracted info for {url}")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {url}: {e}. Response: {response_text}")
            return self._default_error_response(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Error extracting article info for {url}: {e}", exc_info=True)
            return self._default_error_response(str(e))

    def _default_error_response(self, error_message: str) -> dict:
        """Возвращает стандартный словарь с ошибкой."""
        return {
            "title": None,
            "summary": f"LLM parsing error: {error_message}",
            "content": "",
            "rating": None,
            "store_links": {},
        }

    # Методы generate_reminder_message и generate_updated_prompt не используются, но оставлены для соответствия интерфейсу
    async def generate_reminder_message(self, reminder_type: str, user_context: Dict[str, Any]) -> str:
        return ""

    async def generate_updated_prompt(self, prompt: str, history: list[dict], **kwargs) -> str:
        return ""
