"""Tests for BaseParser."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from src.parsers.utils.base_parser import BaseParser


class ConcreteParser(BaseParser):
    """Concrete implementation of BaseParser for testing."""

    def _build_page_urls(self, pages: int) -> list[str]:
        return [self.TARGET_URLS[0]] if self.TARGET_URLS else []

    async def _parse_article(self, article_html, **kwargs):
        return None


@pytest.fixture
def parser():
    return ConcreteParser(default_url="https://example.com")


class TestBaseParserFetchPage:
    def test_fetch_page_saves_html_with_url(self, parser):
        """_save_fetched_html вызывается с URL, не именем класса."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = AsyncMock(return_value="<html></html>")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = MagicMock(return_value=mock_response)
        parser.session = mock_session
        parser._save_fetched_html = AsyncMock()

        url = "https://example.com/article/123"
        asyncio.run(parser._fetch_page(url))

        parser._save_fetched_html.assert_called_once_with("<html></html>", url)

    def test_fetch_page_uses_client_timeout(self, parser):
        """timeout передаётся как aiohttp.ClientTimeout, не int."""
        captured_kwargs = {}

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = AsyncMock(return_value="<html></html>")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        def fake_get(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = fake_get
        parser.session = mock_session
        parser._save_fetched_html = AsyncMock()

        asyncio.run(parser._fetch_page("https://example.com/page"))

        assert "timeout" in captured_kwargs
        assert isinstance(captured_kwargs["timeout"], aiohttp.ClientTimeout)


class TestNormalizeUrl:
    def test_normalize_url_absolute(self, parser):
        result = parser._normalize_url("https://example.com/page")
        assert result == "https://example.com/page"

    def test_normalize_url_relative(self, parser):
        result = parser._normalize_url("/path/to/page")
        assert result == "https://example.com/path/to/page"

    def test_normalize_url_protocol_relative(self, parser):
        result = parser._normalize_url("//example.com/page")
        assert result == "https://example.com/page"

    def test_normalize_url_no_scheme(self, parser):
        result = parser._normalize_url("example.com/page")
        assert result == "https://example.com/page"

    def test_normalize_url_empty(self, parser):
        result = parser._normalize_url("")
        assert result == ""

    def test_normalize_url_relative_no_base(self):
        p = ConcreteParser()  # no default_url
        result = p._normalize_url("/path")
        assert result == ""
