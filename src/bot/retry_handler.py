"""Retry handler utility for GamesParser bot."""

import asyncio
import random
from typing import Any, Callable

from telegram.error import NetworkError, RetryAfter, TimedOut

from src.common.logger import logger


class RetryHandler:
    """Класс для управления повторными попытками и задержками."""

    DEFAULTS = {
        "max_retries": 5,
        "base_delay": 1,
        "backoff_factor": 2,
        "jitter_range": 0.5,
        "min_delay": 1,
        "max_delay": 60,
    }

    def __init__(self, config: dict = None):
        """Инициализация параметров retry-логики."""
        self.config = {**self.DEFAULTS, **(config or {})}
        self.max_retries = self.config["max_retries"]
        self.base_delay = self.config["base_delay"]
        self.backoff_factor = self.config["backoff_factor"]
        self.min_delay = self.config["min_delay"]
        self.max_delay = self.config["max_delay"]
        self.jitter_range = self.config["jitter_range"]

    async def run_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Выполняет функцию с повторными попытками и задержками."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except (TimedOut, NetworkError) as e:
                last_error = e
                delay = self.calculate_delay(attempt)
                logger.warning(
                    "Retry %d/%d after network/timeout error: %s. Waiting %.2f seconds...",
                    attempt + 1,
                    self.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            except RetryAfter as e:
                last_error = e
                delay = e.retry_after
                logger.warning(
                    "Retry %d/%d after rate limit error. Waiting %.2f seconds...",
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception as e:
                last_error = e
                delay = self.calculate_delay(attempt)
                logger.warning(
                    "Retry %d/%d after error: %s. Waiting %.2f seconds...",
                    attempt + 1,
                    self.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
        if last_error:
            raise last_error
        return None

    def calculate_delay(self, attempt: int) -> float:
        """Вычисляет задержку между попытками с учётом экспоненциального роста и джиттера."""
        delay = self.base_delay * (self.backoff_factor**attempt)
        jitter = random.uniform(-self.jitter_range, self.jitter_range)  # noqa: S311
        delay += jitter
        delay = max(self.min_delay, min(delay, self.max_delay))
        return delay


def retry(
    max_retries: int = 5,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter_range: float = 0.5,
    min_delay: float = 1.0,
    max_delay: float = 60.0,
) -> Callable:
    """Decorator to apply retry logic to an async function."""
    config = {
        "max_retries": max_retries,
        "base_delay": base_delay,
        "backoff_factor": backoff_factor,
        "jitter_range": jitter_range,
        "min_delay": min_delay,
        "max_delay": max_delay,
    }
    handler = RetryHandler(config)

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Any:
            return await handler.run_with_retry(func, *args, **kwargs)

        return wrapper

    return decorator
