"""Tests for BaseParser."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
import aiohttp

from src.parsers.utils.base_parser import BaseParser


class ConcreteParser(BaseParser):
    """Concrete implementation of BaseParser for testing."""

    async def fetch_posts(self) -> list:
        return []

    async def stream_posts(self):
        return
        yield  # make it a generator


@pytest.fixture
def parser():
    return ConcreteParser(default_base_url="https://example.com")


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
        p = ConcreteParser()  # no default_base_url
        result = p._normalize_url("/path")
        assert result == ""
