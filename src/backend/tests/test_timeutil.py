from datetime import UTC, date, datetime

from naiad.timeutil import local_date_to_utc, local_day_start_utc, now_utc_naive


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
