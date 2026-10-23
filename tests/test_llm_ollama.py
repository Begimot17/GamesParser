"""Tests for LLMOllama service."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.llm_ollama import LLMOllama


def _mock_client(content=None, error=None):
    response = MagicMock()
    response.json.return_value = {"message": {"content": content}}
    client = MagicMock()
    client.post = AsyncMock(side_effect=error, return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestLLMOllama(unittest.IsolatedAsyncioTestCase):
    async def test_extract_success_sends_json_format(self):
        client = _mock_client('{"title": "T", "store_links": {"steam": "https://s/1", "gog": null}}')
        with patch("src.services.llm_ollama.httpx.AsyncClient", return_value=client):
            result = await LLMOllama(model_name="m").extract_article_info("text", "https://x")

        self.assertEqual(result["title"], "T")
        self.assertEqual(result["store_links"], {"steam": "https://s/1"})
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["model"], "m")
        self.assertFalse(payload["stream"])

    async def test_extract_connection_error_falls_back(self):
        client = _mock_client(error=ConnectionError("ollama down"))
        with patch("src.services.llm_ollama.httpx.AsyncClient", return_value=client):
            result = await LLMOllama().extract_article_info("text", "https://x")

        self.assertIsNone(result["title"])
        self.assertIn("LLM parsing error", result["summary"])


if __name__ == "__main__":
    unittest.main()
