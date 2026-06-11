import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, SQLModel, create_engine

from naiad.api.system import _upcoming_day_runs, _week_series, upcoming_run_candidates
from naiad.config import AppConfig
from naiad.domain.models import Plan, RunHistory
from tests.conftest import MINIMAL_CONFIG_DATA


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_week_series_buckets_runs_by_local_weekday() -> None:
    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(eng) as s:
        s.add(
            RunHistory(
                zone_id="z", sequence_id="seq", started_at=now, triggered_by="cron", liters=12.0
            )
        )
        s.commit()

    with Session(eng) as s:
        series = _week_series(s, "UTC")

    assert len(series) == 7
    today_idx = now.weekday()  # 0=Mon..6=Sun
    assert series[today_idx] == 12.0
    assert sum(series) == 12.0


def test_week_series_empty() -> None:
    with Session(_engine()) as s:
        assert _week_series(s, "Europe/Berlin") == [0.0] * 7


def _config_no_schedule() -> AppConfig:
    """Config whose sequences have no cron schedule, so the only upcoming runs
    are the ones we inject (a running run, in these tests)."""
    cfg = AppConfig.model_validate(MINIMAL_CONFIG_DATA)
    for seq in cfg.sequences.values():
        seq.schedule.cron = None
        seq.schedule.times = []
        seq.schedule.days = []
    return cfg


def test_running_sequence_excluded_from_upcoming_runs() -> None:
    """A run currently executing must NOT appear in the upcoming list — live runs
    are surfaced on the sequence/zone cards instead. With no schedule and only a
    running run in the system, the upcoming list is therefore empty."""
    cfg = _config_no_schedule()
    sched = AsyncIOScheduler(timezone=cfg.timezone)
    with Session(_engine()) as s:
        runs = _upcoming_day_runs(s, cfg, sched)

    assert runs == []


def _plan_at(local_dt: datetime) -> Plan:
    """A one-off seq_1 plan at a local-aware datetime, stored as naive UTC."""
    return Plan(
        id=str(uuid.uuid4()),
        sequence_id="seq_1",
        scheduled_at=local_dt.astimezone(UTC).replace(tzinfo=None),
        duration_min=10,
    )


def test_upcoming_runs_span_first_future_day_only() -> None:
    """The upcoming list covers the next future day that has runs (all of them)
    but stops there — runs on the day after are not included."""
    cfg = _config_no_schedule()
    tz = ZoneInfo(cfg.timezone)
    # Use tomorrow as the first future day so the assertions don't depend on how
    # much of today is left at test time.
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)
    sched = AsyncIOScheduler(timezone=cfg.timezone)
    with Session(_engine()) as s:
        s.add(_plan_at(datetime.combine(tomorrow, time(6, 0), tzinfo=tz)))
        s.add(_plan_at(datetime.combine(tomorrow, time(20, 0), tzinfo=tz)))
        s.add(_plan_at(datetime.combine(day_after, time(6, 0), tzinfo=tz)))
        s.commit()
        runs = _upcoming_day_runs(s, cfg, sched)

    # Both of tomorrow's runs, sorted, and nothing from the day after.
    times = [r.scheduled_at.replace(tzinfo=UTC).astimezone(tz).date() for r in runs]
    assert times == [tomorrow, tomorrow]


def test_upcoming_run_candidates_bounded_and_sorted() -> None:
    """The week-view helper returns every plan inside the window, sorted by fire
    time, and drops plans beyond ``until``."""
    cfg = _config_no_schedule()
    tz = ZoneInfo(cfg.timezone)
    now = datetime.now(UTC)
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    in_window_late = datetime.combine(tomorrow + timedelta(days=4), time(6, 0), tzinfo=tz)
    in_window_early = datetime.combine(tomorrow, time(20, 0), tzinfo=tz)
    beyond = datetime.combine(tomorrow + timedelta(days=10), time(6, 0), tzinfo=tz)

    sched = AsyncIOScheduler(timezone=cfg.timezone)
    with Session(_engine()) as s:
        s.add(_plan_at(in_window_late))
        s.add(_plan_at(in_window_early))
        s.add(_plan_at(beyond))
        s.commit()
        candidates = upcoming_run_candidates(s, cfg, sched, now + timedelta(days=7))

    whens = [when for when, _run in candidates]
    assert whens == sorted(whens)
    assert len(candidates) == 2
    assert all(when <= now + timedelta(days=7) for when in whens)
