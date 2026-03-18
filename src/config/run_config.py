"""Run configuration — controls which parsers and monitors are active."""

from src.config.config import settings


def is_parser_enabled(name: str) -> bool:
    """Returns True if the parser with the given name is enabled in parsers.yml."""
    parser_cfg = settings.PARSERS_CONFIG.get(name, {})
    return bool(parser_cfg.get("enabled", True))


def is_monitor_enabled(name: str) -> bool:
    """Returns True if the monitor with the given name is enabled in monitors.yml."""
    cfg = settings.MONITORS_CONFIG.get(name, {})
    return bool(cfg.get("enabled", True))


def get_monitor_interval(name: str, default: int) -> int:
    """Returns the scan interval for the given monitor, or default if not configured."""
    cfg = settings.MONITORS_CONFIG.get(name, {})
    return int(cfg.get("scan_interval", default))
