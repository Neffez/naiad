import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory, SequenceOverride
from naiad.domain.resume import (
    load_active_runs,
    load_pending_closes,
    load_snapshot,
    save_active_run,
    save_pending_close,
)
from naiad.domain.sequences import (
    MutexConflict,
    NotRunning,
    SequenceRunner,
    SequenceState,
    ValveCleanupInProgress,
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
    watchdog_config = AppConfig.model_validate(data)
    # A zero watchdog (fires immediately) is rejected by config validation, so
    # set it on the validated instance to exercise the runtime watchdog path.
    for seq in watchdog_config.sequences.values():
        seq.watchdog_min = 0

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
    """A failing turn_off must not abort the loop before history is written. The
    unconfirmed close is the safety-critical outcome, so it takes precedence over
    the stop reason in history (close_failed, not ha_disconnect)."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.start("seq_1")
    await asyncio.sleep(0)
    await runner.stop("seq_1", reason="ha_disconnect")

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    assert len(history) == 1
    assert history[0].abort_reason == "close_failed"  # safety precedence
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


async def test_recovery_retry_reuses_already_resumed_task(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A failed reconciliation retry must not start a second recovery task."""
    data = minimal_config.model_dump()
    data["sequences"]["seq_1"]["basis_min_per_zone"] = 30.0
    data["sequences"]["seq_1"]["range"] = [0.0, 60.0]
    data["sequences"]["seq_1"]["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC) - timedelta(minutes=1),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
            switch="switch.zone_a",
        )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    original_reconcile = runner.reconcile_valves
    reconcile_calls = 0

    async def _fail_once(exclude=None) -> None:
        nonlocal reconcile_calls
        reconcile_calls += 1
        if reconcile_calls == 1:
            raise RuntimeError("database unavailable")
        await original_reconcile(exclude)

    runner.reconcile_valves = _fail_once  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="database unavailable"):
        await runner.recover_runs()
    first_task = _task(runner, "seq_1")

    assert await runner.recover_runs() == ["already_resumed"]
    assert _task(runner, "seq_1") is first_task
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


async def test_recover_reconfigured_switch_is_closed_without_resuming(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """Recovery closes the stored physical switch if config now points elsewhere."""
    data = minimal_config.model_dump()
    data["zones"]["zone_a"]["switch"] = "switch.new_valve"
    config = AppConfig.model_validate(data)
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
            switch="switch.old_valve",
        )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    actions = await runner.recover_runs()

    assert actions == ["discarded_reconfigured"]
    assert not runner.any_running()
    with Session(engine) as session:
        assert not load_active_runs(session)
        assert {p.switch for p in load_pending_closes(session)} == {"switch.old_valve"}

    await runner.retry_pending_closes()
    assert "switch.old_valve" in driver.off_calls


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


async def test_pending_close_kept_when_turn_off_unconfirmed(fast_config: AppConfig, engine) -> None:
    """A normally-completed run whose final turn_off could not be confirmed keeps
    a switch-specific PendingClose, but no ActiveRun that crash recovery could resume."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)

    assert not runner.any_running()
    with Session(engine) as session:
        assert not load_active_runs(session)
        assert {p.switch for p in load_pending_closes(session)} == {"switch.zone_a"}


async def test_controlled_close_failure_is_not_resumed_after_restart(
    fast_config: AppConfig, engine
) -> None:
    """A controlled end with an unconfirmed close is retried as a PendingClose,
    never resumed as though the process crashed mid-run."""
    driver = FailingOffDriver()
    runner1 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    await runner1.start("seq_1")
    await asyncio.wait_for(_task(runner1, "seq_1"), timeout=5.0)

    driver.on_calls.clear()
    runner2 = SequenceRunner(fast_config, driver, lambda: Session(engine))
    actions = await runner2.recover_runs()

    assert actions == ["reconciled"]
    assert driver.on_calls == []
    assert not runner2.any_running()


async def test_retry_pending_closes_closes_and_clears(fast_config: AppConfig, engine) -> None:
    """Once recovery has run, the periodic retry closes a valve whose turn_off was
    unconfirmed and clears the record only after HA confirms it off."""
    driver = GatedOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)
    with Session(engine) as session:
        assert not load_active_runs(session)
        assert {p.switch for p in load_pending_closes(session)} == {"switch.zone_a"}

    # HA recovers — the retry should now close the valve and clear the record.
    driver.allow_off = True
    await runner.retry_pending_closes()

    assert "switch.zone_a" in driver.off_calls
    with Session(engine) as session:
        assert not load_active_runs(session)
        assert not load_pending_closes(session)


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


async def test_retry_pending_closes_fast_path_skips_lock_when_idle(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """With nothing to close the retry returns without entering the locked section,
    so an idle plan tick never raises _cleanup_in_progress (which briefly blocks
    fresh starts and config reloads). The locked section still runs once there is
    durable work."""
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    entered = False

    async def _spy() -> None:
        nonlocal entered
        entered = True

    runner._retry_pending_closes_locked = _spy  # type: ignore[method-assign]

    await runner.retry_pending_closes()
    assert entered is False  # fast path: locked section skipped
    assert runner.can_reload_config()

    with Session(engine) as session:
        save_pending_close(session, "switch.zone_a", "zone_a")
    await runner.retry_pending_closes()
    assert entered is True  # work present: locked section runs


async def test_initial_recovery_gate_rejects_fresh_starts(
    fast_config: AppConfig, driver: FakeDriver, engine
) -> None:
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner.require_initial_recovery()

    # Fresh starts are blocked until recovery runs, but config reload stays allowed
    # while idle — otherwise an HA outage at boot would lock the user out of fixing
    # configuration indefinitely (recovery never runs while HA is unreachable).
    assert runner.can_reload_config()
    with pytest.raises(MutexConflict, match="initial valve recovery"):
        await runner.start("seq_1")

    await runner.recover_runs()
    await runner.start("seq_1")
    await runner.stop("seq_1")


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


# ── Per-zone pending closes (multi-zone & reconciliation durability) ───────────


class PerZoneFailingOffDriver(FakeDriver):
    """turn_off raises for switches in ``fail_switches``, succeeds otherwise."""

    def __init__(self, fail_switches: set[str]) -> None:
        super().__init__()
        self.fail_switches = fail_switches

    async def turn_off(self, zone: Any) -> None:
        if zone.switch in self.fail_switches:
            raise RuntimeError("HA unreachable")
        self.off_calls.append(zone.switch)


def _multi_zone_config(minimal_config: AppConfig) -> AppConfig:
    data = minimal_config.model_dump()
    data["sequences"]["multi"] = {
        "label": "Multi",
        "zones": ["zone_a", "zone_b"],
        "basis_min_per_zone": 0.001,
        "range": [0.0, 0.01],
        "watchdog_min": 60,
        "schedule": {"cron": "0 6 * * *"},
    }
    return AppConfig.model_validate(data)


async def test_unconfirmed_close_aborts_sequence_and_persists_per_zone(
    minimal_config: AppConfig, engine
) -> None:
    """When a zone's close cannot be confirmed, the sequence aborts instead of
    advancing (which would leave two valves open), and the open valve is durably
    recorded per-zone with its switch entity so the retry can close it later."""
    config = _multi_zone_config(minimal_config)
    driver = PerZoneFailingOffDriver(fail_switches={"switch.zone_a"})
    runner = SequenceRunner(config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("multi")
    await asyncio.wait_for(_task(runner, "multi"), timeout=5.0)

    # The sequence stopped after zone_a — zone_b was never opened.
    assert "switch.zone_b" not in driver.on_calls
    # zone_a's unconfirmed close is preserved as a per-zone PendingClose (with switch).
    with Session(engine) as session:
        rows = load_pending_closes(session)
    assert {p.zone_id for p in rows} == {"zone_a"}
    assert rows[0].switch == "switch.zone_a"

    # The retry (run no longer live → zone not managed) closes it and clears it.
    driver.fail_switches = set()
    await runner.retry_pending_closes()
    assert "switch.zone_a" in driver.off_calls
    with Session(engine) as session:
        assert not load_pending_closes(session)


async def test_retry_closes_stored_switch_after_zone_removed(
    minimal_config: AppConfig, engine
) -> None:
    """If a config reload removes the zone (or changes its switch), the retry still
    closes the exact entity that was left open, using the switch stored on the
    PendingClose rather than re-resolving the (now stale) zone_id."""
    driver = FakeDriver()
    runner = SequenceRunner(minimal_config, driver, lambda: Session(engine))
    runner._recovery_complete = True
    with Session(engine) as session:
        save_pending_close(session, "switch.old_valve", "ghost_zone")

    await runner.retry_pending_closes()

    assert "switch.old_valve" in driver.off_calls  # exact stale entity closed
    with Session(engine) as session:
        assert not load_pending_closes(session)


async def test_pending_close_reserves_zone(minimal_config: AppConfig, engine) -> None:
    """A zone with an unconfirmed-open valve is reserved: a new run that needs it
    is rejected, so the retry can never close the new run's valve."""
    config = _multi_zone_config(minimal_config)
    driver = FakeDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))
    with Session(engine) as session:
        save_pending_close(session, "switch.zone_a", "zone_a")

    with pytest.raises(ZoneBusy):
        await runner.start("seq_1")  # seq_1 uses zone_a → switch.zone_a


async def test_active_run_reserves_stored_switch(minimal_config: AppConfig, engine) -> None:
    """A crash record blocks a fresh run until its physical switch is closed."""
    runner = SequenceRunner(minimal_config, FakeDriver(), lambda: Session(engine))
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="crashed",
            zone_index=0,
            zone_started_at=datetime.now(UTC),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
            switch="switch.zone_a",
        )

    with pytest.raises(ZoneBusy):
        await runner.start("seq_1")


async def test_retry_active_run_closes_stored_switch_after_repoint(
    minimal_config: AppConfig, engine
) -> None:
    """The ActiveRun fallback closes its stored switch, never a re-pointed config switch."""
    driver = FakeDriver()
    runner = SequenceRunner(minimal_config, driver, lambda: Session(engine))
    runner._recovery_complete = True
    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC),
            zone_planned_min=30.0,
            run_duration_min=30.0,
            triggered_by="cron",
            switch="switch.old_valve",
        )

    await runner.retry_pending_closes()

    assert driver.off_calls == ["switch.old_valve"]
    with Session(engine) as session:
        assert not load_active_runs(session)


async def test_retry_skips_zone_owned_by_live_run(minimal_config: AppConfig, engine) -> None:
    """While a sequence still owns a zone, a pending close for that zone is not
    retried (is_managed guard) — the valve is legitimately open."""
    config = _multi_zone_config(minimal_config)
    driver = FakeDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("multi")
    await asyncio.sleep(0)  # open the first zone
    with Session(engine) as session:
        save_pending_close(session, "switch.zone_a", "zone_a")  # unconfirmed intermediate close

    await runner.retry_pending_closes()
    # zone_a is in the live run's seq.zones → is_managed → not closed, not cleared.
    assert "switch.zone_a" not in driver.off_calls
    with Session(engine) as session:
        assert {p.zone_id for p in load_pending_closes(session)} == {"zone_a"}
    await runner.stop("multi")


async def test_reconcile_failure_records_pending_close(fast_config: AppConfig, engine) -> None:
    """A turn_off that fails during reconciliation is recorded as a pending close,
    so a lingering open valve is retried instead of being lost (no run owns it)."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))

    await runner.reconcile_valves()

    with Session(engine) as session:
        pending = {p.zone_id for p in load_pending_closes(session)}
    # Every configured zone failed to close and is now tracked for retry.
    assert "zone_a" in pending


class BlockingOffDriver(FakeDriver):
    """Pause reconciliation inside turn_off so its start gate can be asserted."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def turn_off(self, zone: Any) -> None:
        self.entered.set()
        await self.release.wait()
        self.off_calls.append(zone.switch)


async def test_reconcile_blocks_new_starts(fast_config: AppConfig, engine) -> None:
    driver = BlockingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    reconcile_task = asyncio.create_task(runner.reconcile_valves())
    await driver.entered.wait()

    assert not runner.can_reload_config()
    with pytest.raises(ValveCleanupInProgress, match="safety cleanup"):
        await runner.start("seq_1")

    driver.release.set()
    await reconcile_task


async def test_legacy_active_run_retry_blocks_fresh_start(fast_config: AppConfig, engine) -> None:
    """Migrated switch-less ActiveRun rows are closed under the cleanup start gate."""
    driver = BlockingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True
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

    retry_task = asyncio.create_task(runner.retry_pending_closes())
    await driver.entered.wait()
    with pytest.raises(ValveCleanupInProgress, match="safety cleanup"):
        await runner.start("seq_1")

    driver.release.set()
    await retry_task


class FailingOnDriver(FakeDriver):
    """turn_on always raises — simulates HA erroring after possibly opening the valve."""

    async def turn_on(self, zone: Any) -> None:
        raise RuntimeError("HA unreachable")


class FailingOnOffDriver(FakeDriver):
    """Both turn_on and turn_off raise — HA fully unreachable."""

    async def turn_on(self, zone: Any) -> None:
        raise RuntimeError("HA unreachable")

    async def turn_off(self, zone: Any) -> None:
        raise RuntimeError("HA unreachable")


async def test_turn_on_failure_closes_immediately_and_aborts(
    fast_config: AppConfig, engine
) -> None:
    """A turn_on failure (valve may be open) is closed *immediately* — not deferred
    to the next plan tick. When that close succeeds, no pending close lingers; the
    run is still recorded as aborted (start_failed)."""
    driver = FailingOnDriver()  # turn_off still works
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True
    started: list[str] = []

    async def _on_started(run_id: str, triggered_by: str, notification: str | None) -> None:
        started.append(run_id)

    runner.on_started = _on_started

    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)

    assert not runner.any_running()
    assert "switch.zone_a" in driver.off_calls  # closed right away, no 60s wait
    with Session(engine) as session:
        rows = load_pending_closes(session)
        history = list(session.exec(select(RunHistory)).all())
    assert rows == []  # immediate close confirmed → nothing left pending
    assert len(history) == 1
    assert history[0].aborted is True
    assert history[0].abort_reason == "start_failed"
    assert started == []


async def test_slow_started_callback_does_not_delay_watchdog_path(
    fast_config: AppConfig, engine
) -> None:
    """Status delivery is best-effort and never holds an opened valve timer."""
    runner = SequenceRunner(fast_config, FakeDriver(), lambda: Session(engine))
    callback_entered = asyncio.Event()
    callback_release = asyncio.Event()

    async def _slow_started(run_id: str, triggered_by: str, notification: str | None) -> None:
        callback_entered.set()
        await callback_release.wait()

    runner.on_started = _slow_started
    await runner.start("seq_1")
    await callback_entered.wait()
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=2.0)
    assert not runner.any_running()

    callback_release.set()
    await asyncio.gather(*runner._background_tasks, return_exceptions=True)


async def test_turn_on_failure_persists_pending_close_when_close_also_fails(
    fast_config: AppConfig, engine
) -> None:
    """If the immediate close after a turn_on failure also fails, the exact switch
    is persisted as a pending close for retry."""
    driver = FailingOnOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)

    with Session(engine) as session:
        rows = load_pending_closes(session)
        history = list(session.exec(select(RunHistory)).all())
    assert {p.switch for p in rows} == {"switch.zone_a"}  # exact entity tracked for retry
    assert not load_active_runs(session)  # controlled abort must never be crash-resumed
    assert history[0].abort_reason == "close_failed"


async def test_unconfirmed_close_marks_history_aborted(fast_config: AppConfig, engine) -> None:
    """A run whose final close is unconfirmed is recorded as aborted (close_failed),
    not as a successful run."""
    driver = FailingOffDriver()
    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    runner._recovery_complete = True

    await runner.start("seq_1")
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=5.0)

    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    assert len(history) == 1
    assert history[0].aborted is True
    assert history[0].abort_reason == "close_failed"


async def test_pending_close_reserves_switch_despite_stale_zone_id(
    minimal_config: AppConfig, engine
) -> None:
    """Reservation is by physical switch, not zone id: a pending close left under an
    old/renamed zone id still blocks a new run that drives the same switch — so the
    retry can never close a switch a fresh run legitimately holds open."""
    driver = FakeDriver()
    runner = SequenceRunner(minimal_config, driver, lambda: Session(engine))

    # Stale record: zone id no longer matches any config zone, but switch.zone_a is
    # the entity that may still be open.
    with Session(engine) as session:
        save_pending_close(session, "switch.zone_a", "old_zone_name")

    # seq_1 (zone_a → switch.zone_a) must be rejected even though its zone id differs.
    with pytest.raises(ZoneBusy):
        await runner.start("seq_1")


async def test_pending_closes_keyed_by_switch_do_not_overwrite(engine) -> None:
    """Two different switches each keep their own pending close — a new close never
    overwrites another switch's record, and clearing one leaves the other."""
    from naiad.domain.resume import clear_pending_close

    with Session(engine) as session:
        save_pending_close(session, "switch.old", "zone_a")
        save_pending_close(session, "switch.new", "zone_a")
        assert {p.switch for p in load_pending_closes(session)} == {"switch.old", "switch.new"}
        clear_pending_close(session, "switch.new")
        assert {p.switch for p in load_pending_closes(session)} == {"switch.old"}


async def test_recover_discards_run_with_under_one_minute_left(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """A run with less than MIN_RESUME_REMAINING_MIN of its zone window left is
    discarded as stale instead of cycling the valve open for a few seconds."""
    data = minimal_config.model_dump()
    config = AppConfig.model_validate(data)

    with Session(engine) as session:
        save_active_run(
            session,
            sequence_id="seq_1",
            zone_index=0,
            zone_started_at=datetime.now(UTC) - timedelta(minutes=29, seconds=30),
            zone_planned_min=30.0,  # 0.5 min left < 1.0 min minimum → stale
            run_duration_min=30.0,
            triggered_by="cron",
        )

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    actions = await runner.recover_runs()
    assert actions == ["closed_stale"]
    assert not runner.any_running()
    assert "switch.zone_a" in driver.off_calls
    with Session(engine) as session:
        assert not load_active_runs(session)


async def test_explicit_override_raises_watchdog(
    minimal_config: AppConfig, driver: FakeDriver, engine
) -> None:
    """An explicit per-zone duration (manual/plan override) is intentional: the
    watchdog is raised above it instead of aborting the run mid-way."""
    data = minimal_config.model_dump()
    config = AppConfig.model_validate(data)
    # A watchdog of 0 fires immediately — without the auto-raise, any run would
    # abort as "watchdog" right away (config validation forbids 0, so set it on
    # the validated instance to exercise the runtime path).
    for seq in config.sequences.values():
        seq.watchdog_min = 0

    runner = SequenceRunner(config, driver, lambda: Session(engine))
    await runner.start("seq_1", override_min=0.005)  # ~0.3s zone
    await asyncio.wait_for(_task(runner, "seq_1"), timeout=2.0)

    assert "switch.zone_a" in driver.off_calls
    with Session(engine) as session:
        history = list(session.exec(select(RunHistory)).all())
    assert len(history) == 1
    assert history[0].aborted is False
    assert history[0].abort_reason is None
