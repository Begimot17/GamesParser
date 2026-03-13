import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from src.config.config import settings


logger = logging.getLogger("GamesParser")


def setup_logger():
    """Настраивает и возвращает логгер."""
    # Prevent duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    log_level = settings.LOG_LEVEL
    logger.setLevel(log_level)

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console Handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # File Handler
    file_handler = RotatingFileHandler("logs/app.log", maxBytes=1024 * 1024 * 5, backupCount=5, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Warning File Handler
    warning_file_handler = RotatingFileHandler("logs/warnings.log", maxBytes=1024 * 1024 * 5, backupCount=2, encoding="utf-8")
    warning_file_handler.setLevel(logging.WARNING)
    warning_file_handler.setFormatter(formatter)
    logger.addHandler(warning_file_handler)

    return logger


# Initialize logger on import
setup_logger()
