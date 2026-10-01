import json
import re
from typing import Any, Dict

from g4f.client import AsyncClient

from src.common.logger import logger
from src.config.config import settings
from src.services.llm_interface import LLMInterface


class LLMG4F(LLMInterface):
    def __init__(self, model_name: str = None):
        self.client = AsyncClient()
        self.model = model_name or settings.LLM_MODEL

    async def generate_response(self, prompt: str, history: list[dict], **kwargs) -> str:
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.insert(0, {"role": "system", "content": prompt})

        logger.info("Sending request to LLM with model %s", self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            web_search=False,
        )
        response_text = response.choices[0].message.content
        logger.info("LLM response: %s...", response_text[:200])
        return response_text

    async def extract_article_info(self, page_text: str, url: str) -> dict:
        """Extract structured information from article text."""
        prompt = """You are an expert in analyzing gaming news. Your task is to extract structured information from article text and return ONLY valid JSON.

JSON format:
{
  "title": "Exact and complete article title",
  "summary": "Brief description of the news (2-3 sentences, most important points)",
  "content": "Main article text, cleaned from ads, navigation and other junk. Keep paragraphs.",
  "rating": null,
  "store_links": {
    "steam": "full_link_if_found",
    "epicgames": "full_link_if_found",
    "gog": "full_link_if_found"
  },
  "game_title": "Game name if mentioned",
  "genre": "Game genre if mentioned",
  "release_date": "Release date if mentioned",
  "platforms": ["List of platforms if mentioned"],
  "price": "Price if mentioned",
  "discount": "Discount amount if mentioned",
  "tags": ["List of relevant tags"]
}

CRITICALLY IMPORTANT:
- Return ONLY JSON, without any other words or comments.
- In `store_links` include ONLY stores with real, full links.
- If any information is missing, use `null` or empty list `[]`.
- Ignore comments, ads and navigation elements.

Article text for analysis:"""

        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": page_text[:8000]}]

        response_text = ""
        try:
            logger.info("Extracting article info from %s using %s", url, self.model)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                web_search=False,
            )
            response_text = response.choices[0].message.content.strip()
            logger.debug("LLM raw response for %s: %s", url, response_text)

            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                logger.warning("No JSON found in LLM response for %s", url)
                return self._default_error_response("No JSON found in response")

            json_str = json_match.group()
            data = json.loads(json_str)

            if "store_links" in data and isinstance(data["store_links"], dict):
                data["store_links"] = {k: v for k, v in data["store_links"].items() if v and "http" in str(v)}

            logger.info("Successfully extracted info for %s", url)
            return data

        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s. Response: %s", url, e, response_text)
            return self._default_error_response(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(
                f"Error extracting article info for {url}: {e}. Response: {response_text!r}",
                exc_info=True,
            )
            return self._default_error_response(str(e))

    def _default_error_response(self, error_message: str) -> dict:
        """Return default error dictionary."""
        return {
            "title": None,
            "summary": f"LLM parsing error: {error_message}",
            "content": "",
            "rating": None,
            "store_links": {},
        }

    async def generate_reminder_message(self, reminder_type: str, user_context: Dict[str, Any]) -> str:
        return ""

    async def generate_updated_prompt(self, prompt: str, history: list[dict], **kwargs) -> str:
        return ""
