from datetime import UTC, date, datetime, timedelta, timezone

from naiad.timeutil import (
    local_date_to_utc,
    local_day_start_utc,
    local_week_start_utc,
    now_utc_naive,
    to_naive_utc,
)


def test_now_utc_naive_has_no_tzinfo() -> None:
    assert now_utc_naive().tzinfo is None


def test_local_day_start_utc_berlin_summer() -> None:
    # 2026-07-01 is CEST (UTC+2) → local midnight is 2026-06-30 22:00 UTC.
    now = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    start = local_day_start_utc("Europe/Berlin", now=now)
    assert start == datetime(2026, 6, 30, 22, 0)
    assert start.tzinfo is None


def test_local_day_start_utc_berlin_winter() -> None:
    # 2026-01-15 is CET (UTC+1) → local midnight is 2026-01-14 23:00 UTC.
    now = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    start = local_day_start_utc("Europe/Berlin", now=now)
    assert start == datetime(2026, 1, 14, 23, 0)


def test_local_day_start_utc_handles_utc_tz() -> None:
    now = datetime(2026, 3, 10, 5, 0, tzinfo=UTC)
    assert local_day_start_utc("UTC", now=now) == datetime(2026, 3, 10, 0, 0)


def test_local_date_to_utc_bounds() -> None:
    d = date(2026, 7, 1)  # CEST
    start = local_date_to_utc("Europe/Berlin", d)
    end = local_date_to_utc("Europe/Berlin", d, end_exclusive=True)
    assert start == datetime(2026, 6, 30, 22, 0)
    assert end == datetime(2026, 7, 1, 22, 0)
    assert start.tzinfo is None and end.tzinfo is None


def test_local_week_start_utc_berlin_summer() -> None:
    # Wed 2026-07-01 (CEST, UTC+2) → Monday 2026-06-29 00:00 local = 2026-06-28 22:00 UTC.
    now = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    start = local_week_start_utc("Europe/Berlin", now=now)
    assert start == datetime(2026, 6, 28, 22, 0)
    assert start.tzinfo is None


def test_to_naive_utc_naive_interpreted_in_local_tz() -> None:
    # A naive 2026-07-01 14:00 in Berlin (CEST) is 12:00 UTC.
    dt = datetime(2026, 7, 1, 14, 0)
    result = to_naive_utc(dt, "Europe/Berlin")
    assert result == datetime(2026, 7, 1, 12, 0)
    assert result.tzinfo is None


def test_to_naive_utc_aware_converted_from_its_offset() -> None:
    # An aware +02:00 value is converted from its own offset, ignoring tz_name.
    dt = datetime(2026, 7, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    result = to_naive_utc(dt, "UTC")
    assert result == datetime(2026, 7, 1, 12, 0)
    assert result.tzinfo is None
