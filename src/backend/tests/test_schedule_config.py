"""Tests for ScheduleConfig: the friendly days+times model, its cron round-trip,
and backward-compatible migration of legacy/advanced cron expressions."""

import pytest

from naiad.config import (
    ScheduleConfig,
    cron_for_time,
    parse_simple_cron,
)

# ── days + times → cron ───────────────────────────────────────────────────────


def test_daily_single_time_to_cron() -> None:
    sched = ScheduleConfig(times=["06:00"])
    assert sched.days == []
    assert sched.to_crons() == ["0 6 * * *"]


def test_multiple_times_produce_one_cron_each() -> None:
    sched = ScheduleConfig(times=["06:00", "21:30"], days=[1, 3, 5])
    assert sched.to_crons() == ["0 6 * * mon,wed,fri", "30 21 * * mon,wed,fri"]


def test_weekdays_emit_names_not_numbers() -> None:
    sched = ScheduleConfig(times=["05:00"], days=[1, 2, 3, 4, 5])
    assert sched.to_crons() == ["0 5 * * mon,tue,wed,thu,fri"]


def test_times_normalized_deduped_and_sorted_days() -> None:
    sched = ScheduleConfig(times=["6:00", "06:00", "21:30"], days=[5, 1, 1])
    assert sched.times == ["06:00", "21:30"]
    assert sched.days == [1, 5]


def test_too_many_times_rejected() -> None:
    with pytest.raises(ValueError, match="At most 5"):
        ScheduleConfig(times=["01:00", "02:00", "03:00", "04:00", "05:00", "06:00"])


def test_invalid_time_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid time"):
        ScheduleConfig(times=["25:00"])


def test_invalid_weekday_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid weekday"):
        ScheduleConfig(times=["06:00"], days=[8])


# ── legacy / advanced cron migration ──────────────────────────────────────────


def test_legacy_daily_cron_migrates_to_picker() -> None:
    sched = ScheduleConfig(cron="0 6 * * *")
    assert sched.cron is None
    assert sched.days == []
    assert sched.times == ["06:00"]


def test_legacy_named_weekday_cron_migrates() -> None:
    sched = ScheduleConfig(cron="30 21 * * mon-fri")
    assert sched.cron is None
    assert sched.days == [1, 2, 3, 4, 5]
    assert sched.times == ["21:30"]


def test_numeric_weekday_cron_kept_as_advanced() -> None:
    # Numeric day-of-week is ambiguous (0=Sun vs 0=Mon), so it is preserved
    # verbatim as an advanced override rather than silently reinterpreted.
    sched = ScheduleConfig(cron="0 5 * * 1")
    assert sched.cron == "0 5 * * 1"
    assert sched.times == []
    assert sched.to_crons() == ["0 5 * * 1"]


def test_interval_cron_kept_as_advanced() -> None:
    sched = ScheduleConfig(cron="*/30 * * * *")
    assert sched.cron == "*/30 * * * *"
    assert sched.to_crons() == ["*/30 * * * *"]


def test_blank_cron_becomes_none() -> None:
    sched = ScheduleConfig(cron="   ")
    assert sched.cron is None
    assert sched.to_crons() == []


def test_empty_schedule_has_no_runs() -> None:
    sched = ScheduleConfig()
    assert sched.to_crons() == []


# ── helper round-trip ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("0 6 * * *", ([], "06:00")),
        ("30 21 * * mon-fri", ([1, 2, 3, 4, 5], "21:30")),
        ("0 8 * * sat,sun", ([6, 7], "08:00")),
        ("0 6 * * 1", None),  # numeric dow → not representable
        ("*/30 * * * *", None),  # interval minute → not representable
        ("0 6 1 * *", None),  # day-of-month set → not representable
    ],
)
def test_parse_simple_cron(expr: str, expected: tuple[list[int], str] | None) -> None:
    assert parse_simple_cron(expr) == expected


def test_cron_for_time_round_trips() -> None:
    for days in ([], [1], [6, 7], [1, 2, 3, 4, 5]):
        cron = cron_for_time("06:30", days)
        parsed = parse_simple_cron(cron)
        assert parsed == (sorted(days), "06:30")
