import httpx

from src.config.config import settings
from src.services.llm_base import ChatLLM


class LLMOllama(ChatLLM):
    """Local LLM through the Ollama HTTP API (CPU-friendly small models)."""

    def __init__(self, model_name: str = None, base_url: str = None):
        self.model = model_name or settings.OLLAMA_MODEL
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.timeout = settings.OLLAMA_TIMEOUT

    async def _chat(self, messages: list[dict], json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
        }
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            return response.json()["message"]["content"]
