"""Configuration for GamesParser project."""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings using Pydantic."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # Debug mode
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Telegram settings
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHANNEL_ID: str

    # Parser settings
    CHECK_INTERVAL: int = 300
    MAX_POSTS_PER_CHECK: int = 5
    REQUEST_TIMEOUT: int = 30
    MAX_TEXT_LENGTH: int = 4000
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )

    # Timing settings
    POST_PROCESSING_DELAY: int = 5
    STREAM_POST_PROCESSING_DELAY: int = 3
    STREAMING_CYCLE_DELAY: int = 600

    # Storage settings
    DB_PATH: str = "news_bot.db"
    TEST_DB_PATH: str = "test_news_bot.db"
    DB_RETENTION_DAYS: int = 90
    TEST_CHANNEL_ID: Optional[str] = None
    SAVE_HTML: bool = False
    HTML_DIR: str = "html_articles"
    SAVE_ALL_FETCHED_HTML: bool = True
    FETCHED_HTML_DIR: str = "fetched_html"

    # Bot command settings
    ADMIN_USER_IDS: list[int] = []

    # LLM settings
    LLM_MODEL: str = "gpt-4o-mini"
    ENABLE_LLM: bool = False  # Set to True to enable LLM data enrichment

    # Steam price monitor settings
    STEAM_SCAN_INTERVAL: int = 43200        # seconds, 12 hours
    STEAM_DISCOUNT_THRESHOLD: int = 90      # % discount threshold for notifications
    STEAM_APPLIST_REFRESH_DAYS: int = 7     # refresh app list every N days

    # EGS price monitor settings
    EGS_SCAN_INTERVAL: int = 43200          # seconds, 12 hours
    EGS_DISCOUNT_THRESHOLD: int = 90        # % discount threshold for notifications

    # Parsers configuration (loaded from YAML)
    PARSERS_CONFIG: Dict[str, Any] = {}

    def load_parsers_config(self):
        """Loads parser configurations from a YAML file."""
        config_path = self.BASE_DIR / "src" / "config" / "parsers.yml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.PARSERS_CONFIG = yaml.safe_load(f)

    def validate_config(self) -> bool:
        """Validates essential configuration."""
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHANNEL_ID)

# Create a global settings instance
settings = Settings()
settings.load_parsers_config()

# Module-level constants (Telegram limits and bot defaults)
GAMES_PARSER_STR: str = "GamesParser"
MAX_MESSAGE_LENGTH: int = 4096
MAX_CAPTION_LENGTH: int = 1024
MAX_MEDIA_GROUP_SIZE: int = 10
RATE_LIMIT_DELAY: float = 2.0
