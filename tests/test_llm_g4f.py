"""Tests for LLMG4F service."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.llm_g4f import LLMG4F


def _make_llm() -> LLMG4F:
    with patch("src.services.llm_g4f.AsyncClient"):
        return LLMG4F(model_name="test-model")


class TestExtractArticleInfo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.llm = _make_llm()

    async def test_extract_article_info_success(self):
        """Валидный JSON-ответ возвращается корректно."""
        valid_json = (
            '{"title": "Game Title", "content": "Some content", '
            '"store_links": {"steam": "https://store.steampowered.com/app/123/"}}'
        )
        mock_response = MagicMock()
        mock_response.choices[0].message.content = valid_json
        self.llm.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await self.llm.extract_article_info("page text", "https://example.com")

        self.assertEqual(result["title"], "Game Title")
        self.assertEqual(result["content"], "Some content")
        self.assertIn("steam", result["store_links"])

    async def test_extract_article_info_invalid_json(self):
        """Не-JSON ответ → возвращает дефолтный словарь."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "This is not JSON at all"
        self.llm.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await self.llm.extract_article_info("page text", "https://example.com")

        self.assertIsNone(result["title"])
        self.assertEqual(result["store_links"], {})
        self.assertIn("LLM parsing error", result["summary"])

    async def test_extract_article_info_timeout(self):
        """TimeoutError → graceful fallback."""
        self.llm.client.chat.completions.create = AsyncMock(side_effect=TimeoutError("timeout"))

        result = await self.llm.extract_article_info("page text", "https://example.com")

        self.assertIsNone(result["title"])
        self.assertEqual(result["store_links"], {})

    async def test_extract_article_info_filters_invalid_store_links(self):
        """store_links без 'http' в значении должны отфильтровываться."""
        valid_json = (
            '{"title": "T", "store_links": '
            '{"steam": "https://store.steampowered.com/app/1/", "gog": null}}'
        )
        mock_response = MagicMock()
        mock_response.choices[0].message.content = valid_json
        self.llm.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await self.llm.extract_article_info("text", "https://example.com")

        self.assertIn("steam", result["store_links"])
        self.assertNotIn("gog", result["store_links"])


if __name__ == "__main__":
    unittest.main()
