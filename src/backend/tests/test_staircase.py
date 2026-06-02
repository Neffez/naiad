"""Tests for the per-zone staircase-timer re-trigger (hardware watchdog support).

When a zone uses an actuator's staircase-light timer, Naiad re-sends "on" before
the timer expires to keep the valve open, and ends the run early (with a
notification) if it can no longer reach the actuator before that timer elapses.
The re-trigger must never outlive the zone's wait — the software watchdog bounds
it so it can't defeat the hardware safety net.
"""

import asyncio
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig, ZoneConfig, staircase_retrigger_interval_min
from naiad.domain.models import RunHistory
from naiad.domain.sequences import (
    _WATCHDOG,
    SequenceRunner,
    _staircase_retrigger_loop,
    _wait_zone,
    zone_run_id,
)

from .conftest import MINIMAL_CONFIG_DATA


class FakeDriver:
    def __init__(self) -> None:
        self.on_calls: list[str] = []
        self.off_calls: list[str] = []

    async def turn_on(self, zone: Any) -> None:
        self.on_calls.append(zone.switch)

    async def turn_off(self, zone: Any) -> None:
        self.off_calls.append(zone.switch)


class FailAfterFirstOnDriver(FakeDriver):
    """turn_on succeeds once (the initial open) then always fails — simulates HA
    becoming unreachable for the re-triggers."""

    async def turn_on(self, zone: Any) -> None:
        self.on_calls.append(zone.switch)
        if len(self.on_calls) > 1:
            raise RuntimeError("HA unreachable")


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _staircase_config(*, duration_min: float, staircase_min: float) -> AppConfig:
    """A single-zone config whose zone_a uses the staircase timer, sized for a
    fast test (sub-second durations)."""
    data = {
        **MINIMAL_CONFIG_DATA,
        "zones": {
            "zone_a": {
                "label": "Zone A",
                "switch": "switch.zone_a",
                "flow_lph": 500.0,
                "staircase_enabled": True,
                "staircase_min": staircase_min,
            },
        },
        "sequences": {
            "seq_1": {
                "label": "Sequence 1",
                "zones": ["zone_a"],
                "basis_min_per_zone": duration_min,
                "range": [0.0, 1.0],
                "watchdog_min": 60,
                "schedule": {"cron": "0 6 * * *"},
            },
        },
    }
    return AppConfig.model_validate(data)


# ── Config model ──────────────────────────────────────────────────────────────


def test_staircase_requires_positive_time() -> None:
    with pytest.raises(ValueError):
        ZoneConfig(label="X", switch="switch.x", flow_lph=1.0, staircase_enabled=True)


def test_retrigger_interval_is_half_the_timer() -> None:
    cfg = ZoneConfig(
        label="X", switch="switch.x", flow_lph=1.0, staircase_enabled=True, staircase_min=20
    )
    assert staircase_retrigger_interval_min(cfg) == 10.0


def test_no_interval_when_disabled() -> None:
    cfg = ZoneConfig(label="X", switch="switch.x", flow_lph=1.0)
    assert staircase_retrigger_interval_min(cfg) is None


# ── _wait_zone / re-trigger loop (direct, deterministic timing) ─────────────────


async def test_staircase_loop_signals_error_when_retrigger_keeps_failing() -> None:
    error = asyncio.Event()

    async def always_fails() -> None:
        raise RuntimeError("HA unreachable")

    # window 0.2s, retry quickly; with no successful "on" the deadline passes.
    await asyncio.wait_for(
        _staircase_retrigger_loop(always_fails, interval_s=0.02, window_s=0.2, error_event=error),
        timeout=2.0,
    )
    assert error.is_set()


async def test_wait_zone_cancels_retrigger_on_watchdog() -> None:
    """The watchdog (software) ends the wait; the re-trigger task must stop too,
    so it can never keep the actuator's hardware timer alive past the run."""
    count = 0

    async def retrigger() -> None:
        nonlocal count
        count += 1

    # Long zone, very short watchdog → _wait_zone returns on the watchdog.
    result = await _wait_zone(
        duration_min=10 / 60,
        watchdog_min=0.2 / 60,
        stop_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        retrigger=retrigger,
        retrigger_interval_min=(0.05 / 60),
        staircase_window_min=(1.0 / 60),
    )
    assert result == _WATCHDOG
    after_watchdog = count
    await asyncio.sleep(0.3)  # well beyond the re-trigger interval
    assert count == after_watchdog  # no re-trigger fired after the wait returned


# ── Full runner integration ─────────────────────────────────────────────────────


async def test_run_retriggers_while_open(engine) -> None:
    # duration ~0.6s, staircase 0.04min (2.4s) → interval 1.2s... too coarse.
    # Use a small staircase so the interval is well under the duration.
    config = _staircase_config(duration_min=0.6 / 60, staircase_min=0.004)
    driver = FakeDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")
    run = runner._runs["seq_1"]
    assert run.task is not None
    await asyncio.wait_for(run.task, timeout=3.0)

    # Initial open plus several re-triggers, and a final close.
    assert driver.on_calls.count("switch.zone_a") > 2
    assert driver.off_calls.count("switch.zone_a") == 1


async def test_no_retrigger_for_plain_zone(engine) -> None:
    data = {
        **MINIMAL_CONFIG_DATA,
        "sequences": {
            "seq_1": {
                "label": "Sequence 1",
                "zones": ["zone_a"],
                "basis_min_per_zone": 0.4 / 60,
                "range": [0.0, 1.0],
                "watchdog_min": 60,
                "schedule": {"cron": "0 6 * * *"},
            },
        },
    }
    config = AppConfig.model_validate(data)
    driver = FakeDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start("seq_1")
    await asyncio.wait_for(runner._runs["seq_1"].task, timeout=3.0)  # type: ignore[arg-type]

    assert driver.on_calls.count("switch.zone_a") == 1  # opened once, no re-trigger
    assert driver.off_calls.count("switch.zone_a") == 1


async def test_retrigger_failure_ends_run_early_with_notification(engine) -> None:
    # Long zone, small staircase window: the initial "on" lands, all re-triggers
    # fail, so the actuator timer lapses → run ends early with abort reason.
    config = _staircase_config(duration_min=30 / 60, staircase_min=0.004)
    driver = FailAfterFirstOnDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    notifications: list[tuple[str, str]] = []

    async def on_notification(message: str, level: str) -> None:
        notifications.append((message, level))

    runner.on_notification = on_notification

    await runner.start("seq_1")
    await asyncio.wait_for(runner._runs["seq_1"].task, timeout=3.0)  # type: ignore[arg-type]

    assert not runner.any_running()
    assert driver.off_calls.count("switch.zone_a") == 1  # still closed defensively
    assert any(level == "warning" for _, level in notifications)

    with Session(engine) as session:
        rows = list(session.exec(select(RunHistory)).all())
    assert len(rows) == 1
    assert rows[0].aborted is True
    assert rows[0].abort_reason == "staircase_retrigger_failed"


async def test_standalone_zone_run_retriggers(engine) -> None:
    """A standalone single-zone run honors the zone's staircase timer too."""
    config = _staircase_config(duration_min=30 / 60, staircase_min=0.004)
    driver = FakeDriver()
    runner = SequenceRunner(config, driver, lambda: Session(engine))

    await runner.start_zone("zone_a", duration_min=0.6 / 60)
    run = runner._runs[zone_run_id("zone_a")]
    assert run.task is not None
    await asyncio.wait_for(run.task, timeout=3.0)

    assert driver.on_calls.count("switch.zone_a") > 2
    assert driver.off_calls.count("switch.zone_a") == 1
