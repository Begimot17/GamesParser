import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class Config:
    # Telegram settings
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    
    # Parser settings
    TARGET_URL: str = os.getenv("TARGET_URL", "https://pikabu.ru/community/steam")
    CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "300"))
    MAX_POSTS_PER_CHECK: int = int(os.getenv("MAX_POSTS_PER_CHECK", "5"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    MAX_TEXT_LENGTH: int = int(os.getenv("MAX_TEXT_LENGTH", "4000"))
    USER_AGENT: str = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    # Storage settings
    DB_PATH: str = os.getenv("DB_PATH", "news_bot.db")
    SAVE_HTML: bool = os.getenv("SAVE_HTML", "false").lower() == "true"
    HTML_DIR: str = os.getenv("HTML_DIR", "html_articles")
    
    # AI settings
    USE_AI: bool = False  # Отключаем AI обработку по умолчанию
    
    @classmethod
    def validate(cls) -> bool:
        return bool(cls.TELEGRAM_BOT_TOKEN and cls.TELEGRAM_CHANNEL_ID) 