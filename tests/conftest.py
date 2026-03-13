"""Shared pytest fixtures for GamesParser tests."""

import os

import pytest

from src.config.config import settings


@pytest.fixture(autouse=False)
def cleanup_test_db():
    """Удаляет тестовую БД до и после каждого теста."""
    db_path = settings.TEST_DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    yield
    if os.path.exists(db_path):
        os.remove(db_path)
