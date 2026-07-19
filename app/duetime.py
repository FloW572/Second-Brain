"""Parse a due date/time string into a timezone-aware datetime.

Kept dependency-free (stdlib only) so it is trivially unit-testable and can be
shared by the capture pipeline, the update tool and the reminder loop.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# A due value that carries only a date (no time) defaults to this local hour,
# so a reminder fires in the morning of that day rather than at midnight.
DEFAULT_DUE_HOUR = 9


def parse_due(value: str | None, tz_name: str) -> datetime | None:
    """ISO string -> aware datetime. 'YYYY-MM-DD' -> that day at 09:00 local."""
    if not value:
        return None
    tz = ZoneInfo(tz_name)
    value = value.strip()
    has_time = "T" in value or " " in value
    try:
        if has_time:
            dt = datetime.fromisoformat(value)
            return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt
        d = date.fromisoformat(value)
        return datetime.combine(d, time(DEFAULT_DUE_HOUR, 0), tzinfo=tz)
    except (ValueError, TypeError):
        return None
