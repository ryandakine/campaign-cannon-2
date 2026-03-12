"""Schedule service — RRULE parsing, posting windows, timezone handling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil.rrule import rrulestr

MAX_SCHEDULE_ENTRIES = 10_000


def generate_schedule(
    *,
    rrule_str: str,
    start_dt: datetime,
    end_dt: datetime | None = None,
    count: int | None = None,
    tz_name: str = "UTC",
) -> list[datetime]:
    """Generate a list of UTC datetimes from an RRULE string.

    Args:
        rrule_str: RFC 5545 RRULE string (e.g. "FREQ=DAILY;INTERVAL=1")
        start_dt: Start datetime (UTC)
        end_dt: Optional end datetime (UTC)
        count: Optional max number of occurrences
        tz_name: Timezone name for display (schedule stored as UTC)

    Returns:
        List of UTC datetimes
    """
    rule = rrulestr(rrule_str, dtstart=start_dt)

    effective_count = count or MAX_SCHEDULE_ENTRIES

    dates: list[datetime] = []
    for dt in rule:
        if end_dt and dt > end_dt:
            break
        if len(dates) >= effective_count:
            break
        # Ensure UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dates.append(dt)

    return dates


def filter_posting_windows(
    dates: list[datetime],
    windows: list[dict[str, Any]],
) -> list[datetime]:
    """Filter dates to only include those within posting windows.

    Windows format: [{"days": [0,1,2,3,4], "start_hour": 9, "end_hour": 17}]
    Days: 0=Monday, 6=Sunday
    """
    if not windows:
        return dates

    filtered = []
    for dt in dates:
        for window in windows:
            days = window.get("days", list(range(7)))
            start_hour = window.get("start_hour", 0)
            end_hour = window.get("end_hour", 24)
            if dt.weekday() in days and start_hour <= dt.hour < end_hour:
                filtered.append(dt)
                break
    return filtered
