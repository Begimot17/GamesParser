from unittest.mock import AsyncMock, patch

import pytest

from src.bot.bot import TelegramNewsBot


@pytest.fixture
def bot():
    return TelegramNewsBot(
        token="test_token",
        channel_id="test_channel",
        message_delay=0.1,
        retry_delay=0.1,
        max_retries=1,
    )


def test_split_text(bot):
    # Test short text
    text = "Short text"
    parts = bot._split_text(text, 10)
    assert len(parts) == 1
    assert parts[0] == text

    # Test long text
    text = "Line 1\nLine 2\nLine 3"
    parts = bot._split_text(text, 5)
    assert len(parts) == 3
    assert parts[0] == "Line 1"
    assert parts[1] == "Line 2"
    assert parts[2] == "Line 3"

    # Test text with long lines
    text = "Very long line that exceeds the limit\nShort line"
    parts = bot._split_text(text, 10)
    assert len(parts) == 2
    assert "Very long line" in parts[0]
    assert parts[1] == "Short line"


@pytest.mark.asyncio
async def test_send_with_retry_success(bot):
    mock_method = AsyncMock(return_value="success")
    result = await bot._send_with_retry(mock_method, "arg1", kwarg1="value1")

    assert result == "success"
    mock_method.assert_called_once_with("arg1", kwarg1="value1")


@pytest.mark.asyncio
async def test_send_with_retry_retry_after(bot):
    mock_method = AsyncMock()
    mock_method.side_effect = [Exception("RetryAfter"), "success"]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await bot._send_with_retry(mock_method)

        assert result == "success"
        assert mock_method.call_count == 2
        mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_send_with_retry_max_retries(bot):
    mock_method = AsyncMock()
    mock_method.side_effect = Exception("Error")

    with pytest.raises(Exception):
        await bot._send_with_retry(mock_method)

    assert mock_method.call_count == bot.max_retries


@pytest.mark.asyncio
async def test_send_message_text_only(bot):
    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as mock_send:
        await bot.send_message("Test message")
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_with_images(bot):
    with patch.object(bot.bot, "send_media_group", new_callable=AsyncMock) as mock_send:
        await bot.send_message("Test message", images=["image1.jpg", "image2.jpg"])
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_long_text(bot):
    long_text = "a" * (bot.max_message_length + 100)
    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as mock_send:
        await bot.send_message(long_text)
        assert mock_send.call_count > 1


@pytest.mark.asyncio
async def test_send_message_error_handling(bot):
    with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = Exception("Error")
        result = await bot.send_message("Test message")
        assert result is False
