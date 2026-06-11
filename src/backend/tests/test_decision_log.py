"""Decision log: every deterministic outcome of the automatic gate path is
persisted with the factor inputs, so "why didn't it water?" is answerable
from the database instead of by code analysis."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import (
    DecisionLog,
    DeferredCronRun,
    RunHistory,
    SequenceOverride,
    SkippedRun,
    UserPreference,
)
from naiad.domain.sequences import SequenceRunner
from naiad.scheduler import (
    _DECISION_LOG_RETENTION_DAYS,
    _log_decision,
    _retry_deferred_cron_runs,
    run_sequence_job,
)
from tests.test_scheduler import FakeDriver, FakeHA


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def fast_config(minimal_config: AppConfig) -> AppConfig:
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 0.001
        seq["range"] = [0.0, 0.01]
    return AppConfig.model_validate(data)


def _decisions(engine) -> list[DecisionLog]:
    with Session(engine) as session:
        return list(session.exec(select(DecisionLog)).all())


async def test_started_run_logs_decision_with_factor_inputs(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)

    assert await run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "started"
    await runner.stop("seq_1")

    rows = _decisions(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row.sequence_id == "seq_1"
    assert row.triggered_by == "cron"
    assert row.decision == "started"
    assert row.reason is None
    assert row.factor_pct is not None and row.factor_pct > 0
    assert row.temp_c == 20.0  # FakeHA current temperature (no max sensor)
    assert row.rain_today_mm == 0.0
    assert row.rain_prob_today_pct == 0.0
    assert row.rain_mode == "forecast"
    assert row.manual_factor is False


async def test_master_off_logs_skip_without_factor_inputs(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    with Session(engine) as s:
        s.add(UserPreference(key="master_on", value="0"))
        s.commit()
    runner = SequenceRunner(fast_config, FakeDriver(), sf)

    assert await run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "skipped"

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].decision == "skipped"
    assert rows[0].reason == "master_off"
    assert rows[0].factor_pct is None
    assert rows[0].temp_c is None


async def test_zero_factor_skip_logs_rain_inputs(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    ha = FakeHA(prec_prob_today="100", prec_today="100")

    assert await run_sequence_job("seq_1", runner, ha, fast_config, sf) == "skipped"

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].reason == "zero_factor"
    assert rows[0].factor_pct == 0.0
    assert rows[0].rain_factor_pct == 0.0
    assert rows[0].rain_today_mm == 100.0
    assert rows[0].rain_prob_today_pct == 100.0


async def test_wind_skip_logs_factor_inputs(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    ha = FakeHA()
    ha._states["binary_sensor.windalarm"] = "on"

    assert await run_sequence_job("seq_wind", runner, ha, fast_config, sf) == "skipped"

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].reason == "wind"
    # The wind gate fires before the start, but the inputs are still recorded.
    assert rows[0].factor_pct is not None
    assert rows[0].temp_c == 20.0


async def test_season_off_skip_is_logged(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)

    assert await run_sequence_job("seq_1", runner, FakeHA(season="off"), fast_config, sf) == (
        "skipped"
    )

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].reason == "season_off"
    assert rows[0].factor_pct == 0.0


async def test_paused_override_and_user_skip_are_logged(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    with Session(engine) as s:
        s.add(SequenceOverride(sequence_id="seq_1", paused=True))
        s.add(
            SkippedRun(
                sequence_id="seq_wind",
                scheduled_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        s.commit()

    assert await run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "skipped"
    assert await run_sequence_job("seq_wind", runner, FakeHA(), fast_config, sf) == "skipped"

    reasons = {row.sequence_id: row.reason for row in _decisions(engine)}
    assert reasons == {"seq_1": "paused", "seq_wind": "user_skipped"}


async def test_transient_conflict_is_not_logged(fast_config: AppConfig) -> None:
    """Busy/conflict outcomes are retried — only the eventual deterministic
    outcome may produce a row, so a retry loop cannot spam the log."""
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)

    assert await run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "started"
    assert await run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "conflict"
    await runner.stop("seq_1")

    assert [row.decision for row in _decisions(engine)] == ["started"]


async def test_expired_deferred_cron_run_is_logged(fast_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    with Session(engine) as session:
        session.add(
            DeferredCronRun(
                sequence_id="seq_1",
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        session.commit()

    await _retry_deferred_cron_runs(runner, FakeHA(), fast_config, sf)

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].reason == "expired"


def test_log_decision_prunes_rows_past_retention() -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    stale = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        days=_DECISION_LOG_RETENTION_DAYS + 1
    )
    with Session(engine) as s:
        s.add(
            DecisionLog(
                sequence_id="seq_1", triggered_by="cron", decision="started", created_at=stale
            )
        )
        s.commit()

    _log_decision(sf, "seq_1", "cron", "skipped", "master_off")

    rows = _decisions(engine)
    assert len(rows) == 1
    assert rows[0].decision == "skipped"


async def test_decisions_endpoint_paginates_and_labels(minimal_config: AppConfig) -> None:
    from naiad.api.history import get_decisions

    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as s:
        s.add(
            DecisionLog(
                sequence_id="seq_1",
                triggered_by="cron",
                decision="started",
                created_at=now - timedelta(hours=1),
                factor_pct=80.0,
            )
        )
        s.add(
            DecisionLog(
                sequence_id="seq_wind",
                triggered_by="cron",
                decision="skipped",
                reason="wind",
                created_at=now,
            )
        )
        s.commit()

    with Session(engine) as s:
        result = await get_decisions(
            _=None, config=minimal_config, session=s, page=1, per_page=1, sequence_id=None
        )

    assert result.total == 2
    assert len(result.items) == 1
    # Newest first.
    assert result.items[0].sequence_id == "seq_wind"
    assert result.items[0].sequence_label == "Lawn"
    assert result.items[0].reason == "wind"

    with Session(engine) as s:
        filtered = await get_decisions(
            _=None, config=minimal_config, session=s, page=1, per_page=50, sequence_id="seq_1"
        )
    assert filtered.total == 1
    assert filtered.items[0].decision == "started"
    assert filtered.items[0].factor_pct == 80.0


async def test_delete_history_clears_decision_log_too(minimal_config: AppConfig) -> None:
    from naiad.api.history import delete_history

    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as s:
        s.add(RunHistory(zone_id="z", sequence_id="seq_1", started_at=now, triggered_by="cron"))
        s.add(
            DecisionLog(
                sequence_id="seq_1", triggered_by="cron", decision="started", created_at=now
            )
        )
        s.add(
            DecisionLog(
                sequence_id="seq_1",
                triggered_by="cron",
                decision="skipped",
                reason="master_off",
                created_at=now - timedelta(days=40),
            )
        )
        s.commit()

    with Session(engine) as s:
        result = await delete_history(_=None, session=s, older_than_days=30)
    assert result.deleted == 0  # counts run rows only; the run is recent
    with Session(engine) as s:
        remaining = list(s.exec(select(DecisionLog)).all())
    assert len(remaining) == 1
    assert remaining[0].decision == "started"

    with Session(engine) as s:
        await delete_history(_=None, session=s, older_than_days=None)
    with Session(engine) as s:
        assert list(s.exec(select(DecisionLog)).all()) == []
