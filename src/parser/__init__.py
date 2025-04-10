"""
Модуль для парсинга сайтов с игровыми новостями.
"""

from .parser_manager import ParserManager
from .utils.description_helper import generate_description
from .utils.logger import setup_logger
from .vgtimes_parser import VGTimesParser
from .pikabu_parser import PikabuParser

__all__ = [
    "PikabuParser",
    "VGTimesParser",
    "ParserManager",
    "generate_description",
    "setup_logger",
]
