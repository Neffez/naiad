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
