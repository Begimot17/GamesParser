"""
Модуль для парсинга сайтов с игровыми новостями.
"""

from .dtf_parser import DTFParser
from .vgtimes_parser import VGTimesParser
from .parser_manager import ParserManager

__all__ = ['DTFParser', 'VGTimesParser', 'ParserManager'] 