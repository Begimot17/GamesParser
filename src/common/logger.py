"""
Provide logging configuration.
"""

import logging
import os
import sys

from src.common.constants import GAMES_PARSER_STR
from src.common.singleton import Singleton


class Logger(metaclass=Singleton):
    log_level_str = os.environ.get("LOG_LEVEL", "DEBUG")

    def __init__(self):
        logging.basicConfig(
            level=logging.INFO,
            format="[%(asctime)s] %(levelname)-8s %(filename)s:%(lineno)d -> %(message)s",
        )

        self.logger = logging.getLogger(GAMES_PARSER_STR)
        self.logger.propagate = False
        self.logger.setLevel(logging.getLevelName(self.log_level_str))

        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "[%(asctime)s] %(levelname)-8s %(filename)s:%(lineno)d -> %(message)s",
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        logging.info("Logger initialized")

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, stacklevel=2, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, stacklevel=2, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, stacklevel=2, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, stacklevel=2, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(msg, *args, stacklevel=2, **kwargs)
