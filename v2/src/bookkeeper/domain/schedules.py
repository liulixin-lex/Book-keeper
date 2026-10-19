"""Schedule expressions for recurring jobs: ``every:<seconds>`` or ``daily:HH:MM``."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse(expression: str) -> tuple[str, int | time]:
    kind, _, value = expression.partition(":")
    if kind == "every":
        seconds = int(value)
        if seconds < 10:
            raise ValueError("interval must be at least 10 seconds")
        return kind, seconds
    if kind == "daily":
        hour, _, minute = value.partition(":")
        return kind, time(int(hour), int(minute))
    raise ValueError(f"unsupported schedule: {expression}")


def next_run(expression: str, after: datetime, timezone: str) -> datetime:
    """First run strictly after ``after`` (aware datetime); result is in UTC."""
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    kind, value = parse(expression)
    if kind == "every":
        assert isinstance(value, int)
        return (after + timedelta(seconds=value)).astimezone(UTC)
    assert isinstance(value, time)
    zone = ZoneInfo(timezone)
    local = after.astimezone(zone)
    candidate = datetime.combine(local.date(), value, tzinfo=zone)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), value, tzinfo=zone)
    return candidate.astimezone(UTC)
