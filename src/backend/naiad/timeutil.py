"""Time-zone helpers.

Datetimes are stored in SQLite as naive UTC (SQLModel strips tzinfo), so query
boundaries must also be naive UTC to compare correctly. These helpers convert
local-calendar boundaries (in the configured app timezone) into naive UTC.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def local_day_start_utc(tz_name: str, now: datetime | None = None) -> datetime:
    """Naive-UTC instant of *today's* local midnight in ``tz_name``."""
    tz = ZoneInfo(tz_name)
    now_local = (now or datetime.now(UTC)).astimezone(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(UTC).replace(tzinfo=None)


def local_date_to_utc(tz_name: str, d: date, *, end_exclusive: bool = False) -> datetime:
    """Naive-UTC instant of local midnight for ``d`` (or the next day if end_exclusive)."""
    tz = ZoneInfo(tz_name)
    target = d + timedelta(days=1) if end_exclusive else d
    midnight_local = datetime(target.year, target.month, target.day, tzinfo=tz)
    return midnight_local.astimezone(UTC).replace(tzinfo=None)


def local_week_start_utc(tz_name: str, now: datetime | None = None) -> datetime:
    """Naive-UTC instant of Monday 00:00 local in the current local week."""
    tz = ZoneInfo(tz_name)
    now_local = (now or datetime.now(UTC)).astimezone(tz)
    monday_local = (now_local - timedelta(days=now_local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday_local.astimezone(UTC).replace(tzinfo=None)


def to_naive_utc(dt: datetime, tz_name: str) -> datetime:
    """Normalize a datetime to naive UTC for storage.

    A naive input is interpreted in ``tz_name`` (the app timezone); an aware input
    is converted from its own offset. The result is naive UTC to match how
    timestamps are stored (SQLModel strips tzinfo without converting).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(UTC).replace(tzinfo=None)
