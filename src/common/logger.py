import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config.config import settings


logger = logging.getLogger("GamesParser")
missing_data_logger = logging.getLogger("GamesParser.MissingData")
audit_logger = logging.getLogger("GamesParser.Audit")


def setup_logger():
    """Настраивает и возвращает логгер."""
    # Prevent duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    log_level = settings.LOG_LEVEL
    logger.setLevel(log_level)

    # Tests point LOG_DIR to a temp dir so they do not write into the bot's real logs
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console Handler — use UTF-8 with replace for Windows compatibility
    stdout_stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    stdout_handler = logging.StreamHandler(stdout_stream)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # File Handler
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1024 * 1024 * 5, backupCount=5, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Warning File Handler
    warning_file_handler = RotatingFileHandler(log_dir / "warnings.log", maxBytes=1024 * 1024 * 5, backupCount=2, encoding="utf-8")
    warning_file_handler.setLevel(logging.WARNING)
    warning_file_handler.setFormatter(formatter)
    logger.addHandler(warning_file_handler)

    # Missing Data Logger
    missing_data_logger.setLevel(logging.WARNING)
    missing_data_handler = RotatingFileHandler(
        log_dir / "missing_data.log", maxBytes=1024 * 1024 * 5, backupCount=3, encoding="utf-8",
    )
    missing_data_handler.setLevel(logging.WARNING)
    missing_data_handler.setFormatter(formatter)
    missing_data_logger.addHandler(missing_data_handler)
    missing_data_logger.propagate = False

    # Audit Logger
    audit_logger.setLevel(logging.INFO)
    audit_handler = RotatingFileHandler(
        log_dir / "audit.log", maxBytes=1024 * 1024 * 10, backupCount=5, encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = False

    return logger


# Initialize logger on import
setup_logger()
