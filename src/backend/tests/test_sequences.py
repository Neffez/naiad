import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory, SequenceOverride
from naiad.domain.resume import load_active_runs, load_snapshot, save_active_run
from naiad.domain.sequences import (
    MutexConflict,
    NotRunning,
    SequenceRunner,
    SequenceState,
    ZoneBusy,
    ZoneNotFound,
    zone_run_id,
)


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


def _task(runner: SequenceRunner, run_id: str) -> asyncio.Task[None]:
    """The asyncio task of an active run (asserts it exists)."""
    run = runner._runs[run_id]
    assert run.task is not None
    return run.task


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
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=2.0)

    assert not runner.any_running()
    assert "switch.zone_a" in driver.on_calls
    assert "switch.zone_a" in driver.off_calls


async def test_history_row_created_at_start(runner: SequenceRunner, engine) -> None:
    """A run shows up in history immediately at start (ended_at unset), then is
    finalized when the zone ends."""
    await runner.start("seq_1")
    task = _task(runner, "seq_1")
    await asyncio.sleep(0)  # let the run open its first zone

    with Session(engine) as session:
        rows = list(session.exec(select(RunHistory)).all())
    assert len(rows) == 1
    assert rows[0].zone_id == "zone_a"
    assert rows[0].ended_at is None  # in-flight: not finalized yet

    await asyncio.wait_for(task, timeout=2.0)
    with Session(engine) as session:
        rows = list(session.exec(select(RunHistory)).all())
    assert len(rows) == 1  # same row finalized, not a second one
    assert rows[0].ended_at is not None
    assert rows[0].duration_min is not None


async def test_mutex_conflict_same_sequence(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    with pytest.raises(MutexConflict):
        await runner.start("seq_1")
    await runner.stop("seq_1")


async def test_stop_clears_no_snapshot(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)  # let task reach asyncio.wait inside _wait_zone
    await runner.stop("seq_1")

    with Session(engine) as session:
        snap = load_snapshot(session, "seq_1")
    assert snap is None
    assert not runner.any_running()


async def test_pause_saves_snapshot(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.pause("seq_1")

    with Session(engine) as session:
        snap = load_snapshot(session, "seq_1")
    assert snap is not None
    assert snap.sequence_id == "seq_1"
    assert not runner.any_running()


async def test_resume_from_snapshot(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    runner1 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner1.start("seq_1")
    await asyncio.sleep(0)
    await runner1.pause("seq_1")

    driver.on_calls.clear()
    driver.off_calls.clear()

    runner2 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner2.start("seq_1")
    await asyncio.wait_for(_task(runner2, "seq_1"), timeout=2.0)

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
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=2.0)

    assert not runner.any_running()
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
    await runner.stop("seq_1", reason="ha_disconnect")

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

    await runner.stop("seq_1")


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
    await runner.stop("seq_1", reason="ha_disconnect")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    assert len(history) == 1
    assert history[0].abort_reason == "ha_disconnect"
    assert not runner.any_running()


async def test_active_run_persisted_during_run_and_cleared_on_completion(
    runner: SequenceRunner, engine
) -> None:
    """ActiveRun is written while a zone runs and cleared on normal completion."""
    await runner.start("seq_1")
    task = _task(runner, "seq_1")
    await asyncio.sleep(0)
    with Session(engine) as session:
        assert load_active_runs(session)

    await asyncio.wait_for(task, timeout=2.0)
    with Session(engine) as session:
        assert not load_active_runs(session)


async def test_active_run_cleared_on_stop(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop("seq_1")
    with Session(engine) as session:
        assert not load_active_runs(session)


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
    actions = await runner.recover_runs()
    assert actions == ["resumed"]
    # The resumed run owns zone_a and re-opens it.
    await asyncio.sleep(0)
    assert "switch.zone_a" in driver.on_calls
    assert runner.status_of("seq_1").state == SequenceState.RUNNING
    await runner.stop("seq_1")


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
    actions = await runner.recover_runs()
    assert actions == ["closed_stale"]
    assert not runner.any_running()
    assert "switch.zone_a" in driver.off_calls  # valve closed
    with Session(engine) as session:
        assert not load_active_runs(session)  # record discarded


async def test_recover_no_record_reconciles(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    actions = await runner.recover_runs()
    assert actions == ["reconciled"]
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
    actions = await runner.recover_runs()
    assert actions == ["discarded"]
    with Session(engine) as session:
        assert not load_active_runs(session)


async def test_recover_resumes_multiple_runs(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """Two concurrent runs interrupted mid-window are both resumed."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 30.0
        seq["range"] = [0.0, 60.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)

    with Session(engine) as session:
        for sid in ("seq_1", "seq_wind"):
            save_active_run(
                session,
                sequence_id=sid,
                zone_index=0,
                zone_started_at=datetime.now(UTC) - timedelta(minutes=1),
                zone_planned_min=30.0,
                run_duration_min=30.0,
                triggered_by="cron",
            )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    actions = await runner.recover_runs()
    assert actions == ["resumed", "resumed"]
    await asyncio.sleep(0)
    assert runner.status_of("seq_1").state == SequenceState.RUNNING
    assert runner.status_of("seq_wind").state == SequenceState.RUNNING
    # Both owned zones stay open; neither is force-closed by reconciliation.
    assert "switch.zone_a" not in driver.off_calls
    assert "switch.zone_b" not in driver.off_calls
    await runner.stop("seq_1")
    await runner.stop("seq_wind")


async def test_stop_when_idle_raises(runner: SequenceRunner) -> None:
    with pytest.raises(NotRunning):
        await runner.stop("seq_1")


async def test_pause_when_idle_raises(runner: SequenceRunner) -> None:
    with pytest.raises(NotRunning):
        await runner.pause("seq_1")


async def test_is_managed_while_running(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    assert runner.is_managed("zone_a") is True
    assert runner.is_managed("zone_b") is False
    await runner.stop("seq_1")


async def test_stop_reason_defaults_to_manual(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop("seq_1")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "manual_stop"


async def test_stop_reason_rain(runner: SequenceRunner, engine) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop("seq_1", reason="rain")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    aborted = [h for h in history if h.aborted]
    assert len(aborted) == 1
    assert aborted[0].abort_reason == "rain"


async def test_status_includes_triggered_by(runner: SequenceRunner) -> None:
    await runner.start("seq_1", triggered_by="cron")
    status = runner.status_of("seq_1")
    assert status.triggered_by == "cron"
    await runner.stop("seq_1")


async def test_status_includes_current_zone(runner: SequenceRunner) -> None:
    await runner.start("seq_1")
    await asyncio.sleep(0)
    status = runner.status_of("seq_1")
    assert status.state == SequenceState.RUNNING
    assert status.current_zone is not None
    assert status.current_zone.zone_id == "zone_a"
    await runner.stop("seq_1")


# ── Parallel runs ─────────────────────────────────────────────────────────────


async def test_two_disjoint_sequences_run_in_parallel(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """seq_1 (zone_a) and seq_wind (zone_b) share no zone → both run at once."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 5.0  # long enough to overlap
        seq["range"] = [0.0, 10.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")
    await runner.start("seq_wind")
    await asyncio.sleep(0)

    assert set(runner.running_run_ids()) == {"seq_1", "seq_wind"}
    assert "switch.zone_a" in driver.on_calls
    assert "switch.zone_b" in driver.on_calls

    await runner.stop("seq_1")
    await runner.stop("seq_wind")


async def test_overlapping_sequences_blocked(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A second sequence sharing a zone with a live run is rejected."""
    data = minimal_config.model_dump()
    # Make seq_wind also use zone_a so it overlaps seq_1.
    data["sequences"]["seq_wind"]["zones"] = ["zone_a", "zone_b"]
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 5.0
        seq["range"] = [0.0, 10.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")
    await asyncio.sleep(0)
    with pytest.raises(ZoneBusy) as exc:
        await runner.start("seq_wind")
    assert "zone_a" in exc.value.zones
    await runner.stop("seq_1")


async def test_parallel_pause_resume_independent(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """Two parallel sequences keep independent pause snapshots."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 5.0
        seq["range"] = [0.0, 10.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")
    await runner.start("seq_wind")
    await asyncio.sleep(0)

    await runner.pause("seq_1")  # pause only seq_1
    with Session(engine) as session:
        assert load_snapshot(session, "seq_1") is not None
        assert load_snapshot(session, "seq_wind") is None
    assert runner.status_of("seq_wind").state == SequenceState.RUNNING

    await runner.stop("seq_wind")


# ── Standalone single-zone runs ───────────────────────────────────────────────


async def test_start_zone_runs_only_that_zone(runner: SequenceRunner, driver: FakeDriver) -> None:
    """A standalone zone run opens exactly the requested zone and completes."""
    await runner.start_zone("zone_b", duration_min=0.001)
    await asyncio.wait_for(_task(runner, zone_run_id("zone_b")), timeout=2.0)

    assert not runner.any_running()
    assert driver.on_calls == ["switch.zone_b"]
    assert "switch.zone_b" in driver.off_calls
    assert "switch.zone_a" not in driver.on_calls  # the rest of any sequence is untouched


async def test_start_zone_unknown_raises(runner: SequenceRunner) -> None:
    with pytest.raises(ZoneNotFound):
        await runner.start_zone("ghost", duration_min=1.0)


async def test_zone_run_parallel_with_disjoint_sequence(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A zone run may run alongside a sequence that does not use that zone."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 5.0
        seq["range"] = [0.0, 10.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")  # zone_a
    await asyncio.sleep(0)
    await runner.start_zone("zone_b", duration_min=5.0)  # disjoint → allowed
    await asyncio.sleep(0)

    assert set(runner.running_run_ids()) == {"seq_1", zone_run_id("zone_b")}
    await runner.stop("seq_1")
    await runner.stop(zone_run_id("zone_b"))


async def test_start_zone_blocked_by_sequence_using_it(runner: SequenceRunner) -> None:
    """Cross-conflict: starting a zone that a running sequence owns is rejected."""
    await runner.start("seq_1")  # uses zone_a
    await asyncio.sleep(0)
    with pytest.raises(ZoneBusy) as exc:
        await runner.start_zone("zone_a", duration_min=1.0)
    assert "zone_a" in exc.value.zones
    await runner.stop("seq_1")


async def test_start_sequence_blocked_by_zone_run(runner: SequenceRunner) -> None:
    """Cross-conflict: starting a sequence whose zone runs standalone is rejected."""
    await runner.start_zone("zone_a", duration_min=5.0)
    await asyncio.sleep(0)
    with pytest.raises(ZoneBusy) as exc:
        await runner.start("seq_1")  # seq_1 uses zone_a
    assert "zone_a" in exc.value.zones
    await runner.stop(zone_run_id("zone_a"))


async def test_zone_run_status_and_is_managed(runner: SequenceRunner) -> None:
    await runner.start_zone("zone_b", duration_min=1.0)
    await asyncio.sleep(0)
    run_id = zone_run_id("zone_b")
    status = runner.status_of(run_id)
    assert status.sequence_id == run_id
    assert status.current_zone is not None
    assert status.current_zone.zone_id == "zone_b"
    assert runner.is_managed("zone_b") is True
    assert runner.is_managed("zone_a") is False
    await runner.stop(run_id)
    # Synthetic state is cleared once the run ends.
    assert not runner.any_running()


async def test_zone_run_records_history(runner: SequenceRunner, engine) -> None:
    await runner.start_zone("zone_b", duration_min=0.001, triggered_by="manual")
    await asyncio.wait_for(_task(runner, zone_run_id("zone_b")), timeout=2.0)
    with Session(engine) as session:
        rows = list(session.exec(select(RunHistory)).all())
    assert len(rows) == 1
    assert rows[0].zone_id == "zone_b"
    assert rows[0].sequence_id == zone_run_id("zone_b")
    assert rows[0].ended_at is not None


async def test_zone_run_stop(runner: SequenceRunner, driver: FakeDriver) -> None:
    await runner.start_zone("zone_b", duration_min=5.0)
    await asyncio.sleep(0)
    await runner.stop(zone_run_id("zone_b"))
    assert not runner.any_running()
    assert "switch.zone_b" in driver.off_calls


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


# ── Durable close retry (unconfirmed turn_off) ──────────────────────────────────


class GatedOffDriver(FakeDriver):
    """turn_off fails until ``allow_off`` is set, then succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self.allow_off = False

    async def turn_off(self, zone: Any) -> None:
        if not self.allow_off:
            raise RuntimeError("HA unreachable")
        self.off_calls.append(zone.switch)


async def test_active_run_kept_when_turn_off_unconfirmed(fast_config: AppConfig, engine) -> None:
    """A normally-completed run whose final turn_off could not be confirmed keeps
    its ActiveRun record, so the open valve is not silently abandoned."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)

    assert not runner.any_running()
    with Session(engine) as session:
        assert load_active_runs(session)  # kept for retry, not cleared


async def test_retry_pending_closes_closes_and_clears(fast_config: AppConfig, engine) -> None:
    """Once recovery has run, the periodic retry closes a valve whose turn_off was
    unconfirmed and clears the record only after HA confirms it off."""
    driver = GatedOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)
    with Session(engine) as session:
        assert load_active_runs(session)  # close failed during the run

    # HA recovers — the retry should now close the valve and clear the record.
    driver.allow_off = True
    await runner.retry_pending_closes()

    assert "switch.zone_a" in driver.off_calls
    with Session(engine) as session:
        assert not load_active_runs(session)


async def test_retry_pending_closes_noop_before_recovery(fast_config: AppConfig, engine) -> None:
    """The retry must not touch valves before initial crash recovery has run —
    recovery may still want to resume a run that owns the zone."""
    driver = GatedOffDriver()
    driver.allow_off = True
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    # _recovery_complete is False by default.
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
        )

    await runner.retry_pending_closes()
    assert driver.off_calls == []  # no-op
    with Session(engine) as session:
        assert load_active_runs(session)  # record untouched


async def test_retry_pending_closes_skips_live_run(runner: SequenceRunner, engine) -> None:
    """A live run's ActiveRun must not be closed/cleared by the retry."""
    runner._recovery_complete = True
    await runner.start("seq_1")
    await asyncio.sleep(0)  # open the zone (writes ActiveRun)

    await runner.retry_pending_closes()
    assert runner.any_running()  # still live
    with Session(engine) as session:
        assert load_active_runs(session)  # not cleared
    await runner.stop("seq_1")
