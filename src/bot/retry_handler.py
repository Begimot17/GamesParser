"""Retry handler utility for GamesParser bot."""

import asyncio
import random
from typing import Any, Callable

from common import logger


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
