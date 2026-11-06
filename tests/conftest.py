"""Shared pytest fixtures for GamesParser tests."""

import os
import tempfile


# Must run before src.common.logger is imported anywhere
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="gamesparser-test-logs-")

import pytest  # noqa: E402

from src.config.config import settings  # noqa: E402


@pytest.fixture(autouse=False)
def cleanup_test_db():
    """Удаляет тестовую БД до и после каждого теста."""
    db_path = settings.TEST_DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    yield
    if os.path.exists(db_path):
        os.remove(db_path)
