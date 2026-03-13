"""Tests for date_utils module."""
import pytest

from src.parsers.utils.date_utils import parse_russian_date


def test_parse_russian_date_full():
    assert parse_russian_date("25 марта 2024") == "2024-03-25"


def test_parse_russian_date_with_time():
    """Строка с временем — дата всё равно парсится."""
    assert parse_russian_date("5 апреля 2025, 23:22") == "2025-04-05"


@pytest.mark.parametrize("month_str,month_num", [
    ("января", 1), ("февраля", 2), ("марта", 3), ("апреля", 4),
    ("мая", 5), ("июня", 6), ("июля", 7), ("августа", 8),
    ("сентября", 9), ("октября", 10), ("ноября", 11), ("декабря", 12),
])
def test_parse_russian_date_all_months(month_str, month_num):
    result = parse_russian_date(f"15 {month_str} 2024")
    assert result == f"2024-{month_num:02d}-15"


def test_parse_russian_date_invalid():
    assert parse_russian_date("invalid string") is None
    assert parse_russian_date("") is None
    assert parse_russian_date("15 unknownmonth 2024") is None


def test_parse_russian_date_none_input():
    assert parse_russian_date(None) is None  # type: ignore[arg-type]
