"""Date parsing utilities for Russian date strings."""

import re
from typing import Optional


MONTHS: dict[str, int] = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def parse_russian_date(text: str) -> Optional[str]:
    """Parse a Russian date string like '25 марта 2024' → '2024-03-25'.

    Returns ISO date string (YYYY-MM-DD) or None if parsing fails.
    """
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip())
    if not m:
        return None
    day_str, month_str, year_str = m.group(1), m.group(2).lower(), m.group(3)
    month = MONTHS.get(month_str)
    if not month:
        return None
    try:
        return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"
    except ValueError:
        return None
