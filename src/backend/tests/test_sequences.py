import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory, SequenceOverride
from naiad.domain.resume import load_snapshot
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
        fast_config.sequences["seq_1"], "seq_1",
    )
    assert basis == 5.0


async def test_db_override_watchdog_min(fast_config: AppConfig, driver: FakeDriver, engine) -> None:
    with Session(engine) as session:
        session.add(SequenceOverride(sequence_id="seq_1", watchdog_min=120))
        session.commit()

    runner = SequenceRunner(fast_config, driver, lambda: Session(engine))
    basis, watchdog = runner._effective_seq_params(
        fast_config.sequences["seq_1"], "seq_1",
    )
    assert watchdog == 120.0
