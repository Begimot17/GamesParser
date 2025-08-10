import json
import re
from typing import Any, Dict

from g4f.client import AsyncClient

from src.services.llm_interface import LLMInterface


class LLMG4F(LLMInterface):
    def __init__(self):
        self.client = AsyncClient()

    async def generate_response(
        self, prompt: str, history: list[dict], **kwargs
    ) -> str:
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.insert(0, {"role": "system", "content": prompt})
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, web_search=False
        )
        return response.choices[0].message.content

    async def generate_reminder_message(
        self, reminder_type: str, user_context: Dict[str, Any]
    ) -> str:
        prompt = f"Generate a reminder message for type: {reminder_type}"
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": str(user_context)}
        ]
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, web_search=False
        )
        return response.choices[0].message.content

    async def generate_updated_prompt(
        self, prompt: str, history: list[dict], **kwargs
    ) -> str:
        system_prompt = "Update the given prompt based on conversation history."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Current prompt: {prompt}\nHistory: {history}"}
        ]
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, web_search=False
        )
        return response.choices[0].message.content

    async def extract_article_info(self, page_text: str, url: str) -> dict:
        """Извлечь структурированную информацию из текста статьи."""
        prompt = """Ты эксперт по анализу игровых новостей. Извлеки информацию из текста статьи и верни ТОЛЬКО валидный JSON:

{
  "title": "Четкий заголовок статьи",
  "summary": "Краткое описание (2-3 предложения о главном)",
  "content": "Основной текст статьи без рекламы, меню и лишней информации",
  "rating": число_или_null,
  "store_links": {
    "Steam": "полная_ссылка_только_если_найдена",
    "Epic Games": "полная_ссылка_только_если_найдена",
    "GOG": "полная_ссылка_только_если_найдена"
  },
  "game_title": "Название игры",
  "genre": "Жанр игры",
  "release_date": "Дата выхода",
  "platforms": ["список_платформ"],
  "price": "Цена",
  "discount": "Размер скидки",
  "tags": ["релевантные_теги"]
}

КРИТИЧЕСКИ ВАЖНО:
- В store_links включай ТОЛЬКО магазины с реальными ссылками
- НЕ добавляй магазин, если ссылки на него нет в тексте
- Ссылки должны быть полными (https://store.steampowered.com/app/123/)
- Если информации нет - указывай null или []
- Фокусируйся только на основном контенте статьи
- Игнорируй комментарии, рекламу, навигацию

Текст:"""

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": page_text[:8000]}  # Ограничиваем длину текста
        ]
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, web_search=False
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Пытаемся извлечь JSON из ответа
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                data = json.loads(json_str)
                
                # Фильтруем пустые store_links
                if 'store_links' in data:
                    data['store_links'] = {k: v for k, v in data['store_links'].items() 
                                         if v and v.strip() and v != "null" and "http" in v}
                
                return data
            else:
                # Если JSON не найден, возвращаем базовую структуру
                return {
                    "title": None,
                    "summary": response_text[:200] if response_text else None,
                    "content": response_text,
                    "rating": None,
                    "store_links": {},
                    "game_title": None,
                    "genre": None,
                    "release_date": None,
                    "platforms": [],
                    "price": None,
                    "discount": None,
                    "tags": []
                }
        except (json.JSONDecodeError, Exception) as e:
            # В случае ошибки возвращаем базовую структуру с исходным текстом
            return {
                "title": None,
                "summary": f"Ошибка парсинга: {str(e)}",
                "content": page_text[:1000],
                "rating": None,
                "store_links": {},
                "game_title": None,
                "genre": None,
                "release_date": None,
                "platforms": [],
                "price": None,
                "discount": None,
                "tags": []
            }
