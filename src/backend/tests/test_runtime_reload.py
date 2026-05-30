from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.runtime_reload import apply_reloaded_config, mutate_config_in_place
from naiad.scheduler import reschedule_sequences, setup_scheduler


class FakeDriver:
    def __init__(self) -> None:
        self.on_calls: list[str] = []
        self.off_calls: list[str] = []

    async def turn_on(self, zone: Any) -> None:
        self.on_calls.append(zone.switch)

    async def turn_off(self, zone: Any) -> None:
        self.off_calls.append(zone.switch)

    def subscribe_state(self, zone: Any, cb: Any) -> None:
        pass


class FakeHA:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def subscribe_state_changes(self, cb: Any) -> None:
        self.callbacks.append(cb)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return lambda: Session(engine)


def _add_zone_and_sequence(config: AppConfig) -> AppConfig:
    data = config.model_dump()
    data["zones"]["zone_c"] = {"label": "Zone C", "switch": "switch.zone_c", "flow_lph": 100.0}
    data["sequences"]["seq_new"] = {
        "label": "New",
        "zones": ["zone_c"],
        "basis_min_per_zone": 10,
        "watchdog_min": 30,
        "schedule": {"cron": "0 7 * * *"},
    }
    data["sequences"]["seq_wind"]["enabled"] = False
    return AppConfig.model_validate(data)


def _job_ids(scheduler) -> set[str]:
    return {j.id for j in scheduler.get_jobs()}


def _has_cron(scheduler, seq_id: str) -> bool:
    # A sequence registers one cron job per scheduled time, id "cron-<seq>#<i>".
    return any(j.id.startswith(f"cron-{seq_id}#") for j in scheduler.get_jobs())


# ── mutate_config_in_place ────────────────────────────────────────────────────


def test_mutate_preserves_identity_and_updates_fields(minimal_config: AppConfig) -> None:
    current = minimal_config
    original_id = id(current)
    fresh = _add_zone_and_sequence(minimal_config)

    mutate_config_in_place(current, fresh)

    assert id(current) == original_id  # same object the runtime holds by reference
    assert "zone_c" in current.zones
    assert "seq_new" in current.sequences
    assert current.sequences["seq_wind"].enabled is False


# ── reschedule_sequences ──────────────────────────────────────────────────────


def test_reschedule_adds_removes_and_keeps_plan_tick(
    minimal_config: AppConfig, session_factory
) -> None:
    driver = FakeDriver()
    ha = FakeHA()
    runner = SequenceRunner(minimal_config, driver, session_factory)
    scheduler = setup_scheduler(minimal_config, runner, ha, session_factory)

    assert _job_ids(scheduler) == {
        "cron-seq_1#0",
        "cron-seq_wind#0",
        "plan-tick",
        "fallback-temp-max",
    }

    fresh = _add_zone_and_sequence(minimal_config)
    mutate_config_in_place(minimal_config, fresh)
    reschedule_sequences(scheduler, minimal_config, runner, ha, session_factory)

    assert _has_cron(scheduler, "seq_1")
    assert _has_cron(scheduler, "seq_new")  # newly enabled sequence
    assert not _has_cron(scheduler, "seq_wind")  # now disabled
    assert "plan-tick" in _job_ids(scheduler)  # untouched


# ── tracker rebuild ───────────────────────────────────────────────────────────


async def test_tracker_rebuild_picks_up_new_zone(
    minimal_config: AppConfig, session_factory, engine
) -> None:
    ha = FakeHA()
    tracker = LiterTracker(ha, minimal_config, session_factory, lambda _z: False)

    fresh = _add_zone_and_sequence(minimal_config)
    mutate_config_in_place(minimal_config, fresh)
    tracker.rebuild_zone_map()

    on_at = datetime(2026, 5, 29, 6, 0, tzinfo=UTC)
    await tracker._handle_state_change(
        "switch.zone_c", {"state": "on", "last_changed": on_at.isoformat()}
    )
    await tracker._handle_state_change(
        "switch.zone_c",
        {"state": "off", "last_changed": (on_at + timedelta(minutes=60)).isoformat()},
    )

    with Session(engine) as session:
        rows = list(session.exec(select(RunHistory)).all())
    assert len(rows) == 1
    assert rows[0].zone_id == "zone_c"


# ── apply_reloaded_config (coordinator) ───────────────────────────────────────


async def test_apply_reloaded_config_end_to_end(minimal_config: AppConfig, session_factory) -> None:
    driver = FakeDriver()
    ha = FakeHA()
    runner = SequenceRunner(minimal_config, driver, session_factory)
    scheduler = setup_scheduler(minimal_config, runner, ha, session_factory)
    tracker = LiterTracker(ha, minimal_config, session_factory, runner.is_managed)

    fresh = _add_zone_and_sequence(minimal_config)
    apply_reloaded_config(
        minimal_config,
        fresh,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
    )

    # Runner sees the new sequence through the shared, mutated config.
    assert "seq_new" in minimal_config.sequences
    assert _has_cron(scheduler, "seq_new")
    assert "switch.zone_c" in tracker._entity_to_zone
