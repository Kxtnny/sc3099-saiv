"""Shared date and time display: the backend works in UTC, the dashboard shows SGT."""

from datetime import datetime, timedelta, timezone
from typing import Any

SINGAPORE_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Singapore")


def format_singapore_time(value: Any, *, seconds: bool = False) -> str:
    """Show a backend UTC timestamp in Singapore time."""
    if not isinstance(value, str) or not value:
        return "N/A"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    time_format = "%H:%M:%S" if seconds else "%H:%M"
    return parsed.astimezone(SINGAPORE_TIMEZONE).strftime(f"%Y-%m-%d {time_format} SGT")
