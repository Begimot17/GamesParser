"""Album sending falls back to uploading bytes, then to text, when Telegram cannot fetch photo URLs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from src.bot.bot import TelegramNewsBot
from src.bot.retry_handler import RetryHandler


URL = "https://cdn.example.com/img.jpg"


def make_bot() -> TelegramNewsBot:
    bot = TelegramNewsBot(token="123:abc", channel_id="@test", config={"validate_images": False})
    bot.bot = MagicMock()
    bot.bot.send_media_group = AsyncMock()
    bot.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
    bot.http_client = MagicMock(is_closed=False)
    bot.http_client.get = AsyncMock(
        return_value=SimpleNamespace(content=b"\xff\xd8jpeg", raise_for_status=lambda: None),
    )
    return bot


@pytest.mark.asyncio
async def test_curl_failed_uploads_bytes():
    bot = make_bot()
    bot.bot.send_media_group.side_effect = [
        BadRequest('Failed to send message #1 with the error message "webpage_curl_failed"'),
        (SimpleNamespace(message_id=5),),
    ]

    ref = await bot.send_message("<b>Game</b> free", images=[URL])

    assert ref.message_id == 5 and ref.is_caption
    second = bot.bot.send_media_group.call_args_list[1].kwargs["media"]
    assert second[0].media.input_file_content == b"\xff\xd8jpeg"
    assert second[0].caption == "<b>Game</b> free"
    bot.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_upload_failure_falls_back_to_text():
    bot = make_bot()
    bot.bot.send_media_group.side_effect = BadRequest("webpage_curl_failed")
    bot.http_client.get.side_effect = Exception("download failed")

    ref = await bot.send_message("Game free", images=[URL])

    assert ref.message_id == 7 and not ref.is_caption
    assert bot.bot.send_media_group.await_count == 1


@pytest.mark.asyncio
async def test_other_bad_request_is_raised():
    bot = make_bot()
    bot.bot.send_media_group.side_effect = BadRequest("Can't parse entities")

    with pytest.raises(BadRequest):
        await bot.send_message("Game free", images=[URL])


@pytest.mark.asyncio
async def test_bad_request_is_not_retried():
    func = AsyncMock(side_effect=BadRequest("webpage_curl_failed"))

    with pytest.raises(BadRequest):
        await RetryHandler({"max_retries": 5, "base_delay": 0}).run_with_retry(func)

    assert func.await_count == 1


import aiohttp  # noqa: E402


def _http_error(status):
    return aiohttp.ClientResponseError(request_info=None, history=(), status=status)


@pytest.mark.asyncio
async def test_permanent_http_error_not_retried():
    calls = 0

    async def func():
        nonlocal calls
        calls += 1
        raise _http_error(404)

    with pytest.raises(aiohttp.ClientResponseError):
        await RetryHandler({"max_retries": 5, "base_delay": 0, "min_delay": 0}).run_with_retry(func)
    assert calls == 1


@pytest.mark.asyncio
async def test_transient_http_error_retried():
    calls = 0

    async def func():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _http_error(503)
        return "ok"

    result = await RetryHandler({"max_retries": 5, "base_delay": 0, "min_delay": 0}).run_with_retry(func)
    assert result == "ok" and calls == 3
