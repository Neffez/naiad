from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, SQLModel, create_engine

from naiad.api.system import _running_runs, _upcoming_day_runs, _week_series
from naiad.config import AppConfig
from naiad.domain.models import RunHistory
from naiad.domain.sequences import SequenceState, SequenceStatus, ZoneProgress, zone_run_id
from tests.conftest import MINIMAL_CONFIG_DATA


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


class _FakeRunner:
    """Minimal runner stub exposing iter_runs() for the upcoming-runs helpers."""

    def __init__(self, *statuses: SequenceStatus) -> None:
        self._statuses = list(statuses)

    def iter_runs(self) -> list[SequenceStatus]:
        return self._statuses


def _idle_runner() -> _FakeRunner:
    return _FakeRunner()


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


def test_running_sequence_appears_in_today_runs() -> None:
    """A sequence run that has already started must still appear in today's list,
    flagged in_progress — otherwise an evening run would make the list jump to
    tomorrow the moment it begins."""
    cfg = _config_no_schedule()
    started = datetime.now(UTC) - timedelta(minutes=5)
    runner = _FakeRunner(
        SequenceStatus(
            state=SequenceState.RUNNING,
            sequence_id="seq_1",
            current_zone=ZoneProgress(zone_id="zone_a", started_at=started, duration_min=30),
        ),
    )
    sched = AsyncIOScheduler(timezone=cfg.timezone)
    with Session(_engine()) as s:
        runs = _upcoming_day_runs(s, cfg, sched, runner)

    assert len(runs) == 1
    assert runs[0].sequence_id == "seq_1"
    assert runs[0].in_progress is True


def test_idle_runner_yields_no_running_run() -> None:
    cfg = _config_no_schedule()
    with Session(_engine()) as s:
        assert _running_runs(_idle_runner(), s, cfg) == []


def test_running_single_zone_uses_zone_label_and_duration() -> None:
    cfg = _config_no_schedule()
    started = datetime.now(UTC)
    runner = _FakeRunner(
        SequenceStatus(
            state=SequenceState.RUNNING,
            sequence_id=zone_run_id("zone_b"),
            current_zone=ZoneProgress(zone_id="zone_b", started_at=started, duration_min=10),
        )
    )
    with Session(_engine()) as s:
        runs = _running_runs(runner, s, cfg)

    assert len(runs) == 1
    run = runs[0]
    assert run.sequence_id == "zone_b"
    assert run.sequence_label == "Zone B"
    assert run.duration_min == 10
    assert run.in_progress is True
