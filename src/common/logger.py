import logging
import sys
from logging.handlers import RotatingFileHandler

from src.config.config import Config


def setup_logger():
    """Настраивает и возвращает логгер."""
    log_level = Config.LOG_LEVEL
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)

    # Formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console Handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # File Handler
    file_handler = RotatingFileHandler("logs/app.log", maxBytes=1024 * 1024 * 5, backupCount=5)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Warning File Handler
    warning_file_handler = RotatingFileHandler("logs/warnings.log", maxBytes=1024 * 1024 * 5, backupCount=2)
    warning_file_handler.setLevel(logging.WARNING)
    warning_file_handler.setFormatter(formatter)
    logger.addHandler(warning_file_handler)

    return logger


logger = setup_logger()
