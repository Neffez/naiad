import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory, SequenceOverride
from naiad.domain.resume import load_active_run, load_snapshot, save_active_run
from naiad.domain.sequences import MutexConflict, NotRunning, SequenceRunner, SequenceState


class FakeDriver:
    def __init__(self) -> None:
        self.on_calls: list[str] = []
        self.off_calls: list[str] = []

    async def turn_on(self, zone: Any) -> None:
        self.on_calls.append(zone.switch)

    async def turn_off(self, zone: Any) -> None:
        self.off_calls.append(zone.switch)

    def subscribe_state(self, zone: Any, cb: Callable[[bool, datetime], None]) -> None:
        pass


class FailingOffDriver(FakeDriver):
    """Driver whose turn_off always raises — simulates HA being unreachable."""

    def __init__(self) -> None:
        super().__init__()
        self.off_attempts = 0

    async def turn_off(self, zone: Any) -> None:
        self.off_attempts += 1
        raise RuntimeError("HA unreachable")


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def fast_config(minimal_config: AppConfig) -> AppConfig:
    """Config with near-zero zone duration for fast tests."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 0.001
        seq["range"] = [0.0, 0.01]
    return AppConfig.model_validate(data)


@pytest.fixture
def driver() -> FakeDriver:
    return FakeDriver()


@pytest.fixture
def runner(fast_config: AppConfig, driver: FakeDriver, engine) -> SequenceRunner:
    return SequenceRunner(fast_config, driver, lambda: Session(engine))


async def test_normal_completion(runner: SequenceRunner, driver: FakeDriver) -> None:
    await runner.start("seq_1")
    task = runner._task
    assert task is not None
    await asyncio.wait_for(task, timeout=2.0)

    assert runner.status().state == SequenceState.IDLE
    assert "switch.zone_a" in driver.on_calls
    assert "switch.zone_a" in driver.off_calls


async def test_mutex_conflict(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    with pytest.raises(MutexConflict):
        await runner.start("seq_1")
    await runner.stop()


async def test_stop_clears_no_snapshot(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)  # let task reach asyncio.wait inside _wait_zone
    await runner.stop()

    with Session(engine) as session:
        snap = load_snapshot(session, "seq_1")
    assert snap is None
    assert runner.status().state == SequenceState.IDLE


async def test_pause_saves_snapshot(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.pause()

    with Session(engine) as session:
        snap = load_snapshot(session, "seq_1")
    assert snap is not None
    assert snap.sequence_id == "seq_1"
    assert runner.status().state == SequenceState.IDLE


async def test_resume_from_snapshot(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    runner1 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner1.start("seq_1")
    await asyncio.sleep(0)
    await runner1.pause()

    driver.on_calls.clear()
    driver.off_calls.clear()

    runner2 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner2.start("seq_1")
    task = runner2._task
    assert task is not None
    await asyncio.wait_for(task, timeout=2.0)

    assert "switch.zone_a" in driver.on_calls


async def test_watchdog_aborts_run(minimal_config: AppConfig, driver: FakeDriver, engine) -> None:
    """running→aborted (watchdog): when the watchdog fires before the zone
    completes, the zone is turned off and the run is recorded as aborted."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 0.02  # ~1.2s nominal zone duration
        seq["range"] = [0.0, 0.04]
        seq["watchdog_min"] = 0  # watchdog fires immediately
    watchdog_config = AppConfig.model_validate(data)

    runner = SequenceRunner(watchdog_config, driver, lambda: Session(engine))
    await runner.start("seq_1")
    task = runner._task
    assert task is not None
    await asyncio.wait_for(task, timeout=2.0)

    assert runner.status().state == SequenceState.IDLE
    assert "switch.zone_a" in driver.off_calls

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "watchdog"


async def test_stop_reason_ha_disconnect(runner: SequenceRunner, engine) -> None:
    """running→aborted (ha_disconnect): a disconnect-triggered stop is recorded."""
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop(reason="ha_disconnect")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "ha_disconnect"


# ── Valve reconciliation & turn_off resilience (C-1) ──────────────────────────


async def test_reconcile_turns_off_all_zones_when_idle(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.reconcile_valves()
    assert set(driver.off_calls) == {"switch.zone_a", "switch.zone_b"}


async def test_reconcile_skips_running_zone(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.start("seq_1")  # zone_a
    await asyncio.sleep(0)  # let the run reach its first zone
    driver.off_calls.clear()

    await runner.reconcile_valves()
    # zone_a is owned by the live run and must not be force-closed
    assert "switch.zone_a" not in driver.off_calls

    await runner.stop()


async def test_safe_turn_off_retries_then_returns_false(fast_config: AppConfig, engine) -> None:
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    zone_cfg = fast_config.zones["zone_a"]

    ok = await runner._safe_turn_off(zone_cfg, "zone_a", attempts=3, backoff_s=0.0)
    assert ok is False
    assert driver.off_attempts == 3


async def test_safe_turn_off_success(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    ok = await runner._safe_turn_off(fast_config.zones["zone_a"], "zone_a")
    assert ok is True
    assert driver.off_calls == ["switch.zone_a"]


async def test_run_records_history_even_if_turn_off_fails(fast_config: AppConfig, engine) -> None:
    """A failing turn_off must not abort the loop before history is written."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop(reason="ha_disconnect")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    assert len(history) == 1
    assert history[0].abort_reason == "ha_disconnect"
    assert runner.status().state == SequenceState.IDLE


async def test_active_run_persisted_during_run_and_cleared_on_completion(
    runner: SequenceRunner, engine
) -> None:
    """ActiveRun is written while a zone runs and cleared on normal completion."""
    await runner.start("seq_1")
    await asyncio.sleep(0)
    with Session(engine) as session:
        assert load_active_run(session) is not None

    await asyncio.wait_for(runner._task, timeout=2.0)  # type: ignore[arg-type]
    with Session(engine) as session:
        assert load_active_run(session) is None


async def test_active_run_cleared_on_stop(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop()
    with Session(engine) as session:
        assert load_active_run(session) is None


async def test_recover_resumes_fresh_run(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A run interrupted within its zone window is resumed for the remaining time."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 30.0  # 30-min zone window
        seq["range"] = [0.0, 60.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)

    # Simulate a crash 1 minute into a 30-minute zone of seq_1 (zone_a).
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC) - timedelta(minutes=1),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
        )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    action = await runner.recover_run()
    assert action == "resumed"
    # The resumed run owns zone_a and re-opens it.
    await asyncio.sleep(0)
    assert "switch.zone_a" in driver.on_calls
    assert runner.status().state == SequenceState.RUNNING
    assert runner.status().sequence_id == "seq_1"
    await runner.stop()


async def test_recover_closes_stale_run(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A run whose zone window already elapsed is closed, not resumed."""
    data = minimal_config.model_dump()
    config = AppConfig.model_validate(data)

    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC) - timedelta(minutes=90),
            zone_planned_min=30.0,  # elapsed 90 >= 30 → stale
            run_duration_min=30.0,
            triggered_by="cron",
        )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    action = await runner.recover_run()
    assert action == "closed_stale"
    assert runner.status().state == SequenceState.IDLE
    assert "switch.zone_a" in driver.off_calls  # valve closed
    with Session(engine) as session:
        assert load_active_run(session) is None  # record discarded


async def test_recover_no_record_reconciles(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    action = await runner.recover_run()
    assert action == "reconciled"
    assert set(driver.off_calls) == {"switch.zone_a", "switch.zone_b"}


async def test_recover_discards_unknown_sequence(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="ghost",
            zone_index=0,
            zone_started_at=datetime.now(UTC),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
        )
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    action = await runner.recover_run()
    assert action == "discarded"
    with Session(engine) as session:
        assert load_active_run(session) is None


async def test_stop_when_idle_raises(runner: SequenceRunner) -> None:
    with pytest.raises(NotRunning):
        await runner.stop()


async def test_pause_when_idle_raises(runner: SequenceRunner) -> None:
    with pytest.raises(NotRunning):
        await runner.pause()


async def test_is_managed_while_running(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    assert runner.is_managed("zone_a") is True
    assert runner.is_managed("zone_b") is False
    await runner.stop()


async def test_stop_reason_defaults_to_manual(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop()

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "manual_stop"


async def test_stop_reason_rain(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop(reason="rain")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "rain"


async def test_status_includes_triggered_by(runner: SequenceRunner) -> None:
    await runner.start("seq_1", triggered_by="cron")
    status = runner.status()
    assert status.triggered_by == "cron"
    await runner.stop()


async def test_status_includes_current_zone(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    status = runner.status()
    assert status.state == SequenceState.RUNNING
    assert status.current_zone is not None
    assert status.current_zone.zone_id == "zone_a"
    await runner.stop()


async def test_db_override_basis_min(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    with Session(engine) as session:
        session.add(SequenceOverride(sequence_id="seq_1", basis_min_per_zone=5))
        session.commit()

    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    basis, watchdog = runner._effective_seq_params(
        fast_config.sequences["seq_1"],
        "seq_1",
    )
    assert basis == 5.0


async def test_db_override_watchdog_min(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    with Session(engine) as session:
        session.add(SequenceOverride(sequence_id="seq_1", watchdog_min=120))
        session.commit()

    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    basis, watchdog = runner._effective_seq_params(
        fast_config.sequences["seq_1"],
        "seq_1",
    )
    assert watchdog == 120.0
