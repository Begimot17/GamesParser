from g4f.client import AsyncClient

from src.config.config import settings
from src.services.llm_base import ChatLLM


class LLMG4F(ChatLLM):
    def __init__(self, model_name: str = None):
        self.client = AsyncClient()
        self.model = model_name or settings.LLM_MODEL

    async def _chat(self, messages: list[dict], json_mode: bool = False) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            web_search=False,
        )
        return response.choices[0].message.content
