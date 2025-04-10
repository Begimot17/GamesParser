"""
Модуль для парсинга сайтов с игровыми новостями.
"""

from .dtf_parser import DTFParser
from .vgtimes_parser import VGTimesParser
from .parser_manager import ParserManager
from .utils.description_helper import generate_description
from .utils.logger import setup_logger

__all__ = ['DTFParser', 'VGTimesParser', 'ParserManager', 'generate_description', 'setup_logger'] 