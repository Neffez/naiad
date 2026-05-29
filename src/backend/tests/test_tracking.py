from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import RunHistory
from naiad.domain.tracking import LiterTracker
from naiad.ha_client import StateCallback


class FakeHA:
    """Captures the state-change callback that LiterTracker registers."""

    def __init__(self) -> None:
        self.callback: StateCallback | None = None

    def subscribe_state_changes(self, callback: StateCallback) -> None:
        self.callback = callback


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _history(engine) -> list[RunHistory]:
    with Session(engine) as session:
        return list(session.exec(select(RunHistory)).all())


def _make_tracker(
    config: AppConfig, engine, *, managed: set[str] | None = None
) -> tuple[LiterTracker, FakeHA]:
    managed = managed or set()
    ha = FakeHA()
    tracker = LiterTracker(
        ha,  # type: ignore[arg-type]
        config,
        lambda: Session(engine),
        lambda zone_id: zone_id in managed,
    )
    return tracker, ha


def _state(value: str, ts: datetime) -> dict[str, Any]:
    return {"state": value, "last_changed": ts.isoformat()}


def test_subscribes_on_construction(minimal_config: AppConfig, engine) -> None:
    _tracker, ha = _make_tracker(minimal_config, engine)
    assert ha.callback is not None


async def test_external_on_off_records_history(minimal_config: AppConfig, engine) -> None:
    tracker, _ = _make_tracker(minimal_config, engine)
    on_at = datetime(2026, 5, 29, 6, 0, tzinfo=UTC)
    off_at = on_at + timedelta(minutes=30)

    await tracker._handle_state_change("switch.zone_a", _state("on", on_at))
    await tracker._handle_state_change("switch.zone_a", _state("off", off_at))

    rows = _history(engine)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.zone_id == "zone_a"
    assert entry.sequence_id == ""
    assert entry.triggered_by == "external"
    assert entry.aborted is False
    assert entry.duration_min == pytest.approx(30.0)
    # zone_a flows 500 L/h → 30 min ≈ 250 L
    assert entry.liters == pytest.approx(250.0)


async def test_managed_zone_is_skipped(minimal_config: AppConfig, engine) -> None:
    """A zone owned by the SequenceRunner is recorded by the runner, not the tracker."""
    tracker, _ = _make_tracker(minimal_config, engine, managed={"zone_a"})
    on_at = datetime(2026, 5, 29, 6, 0, tzinfo=UTC)

    await tracker._handle_state_change("switch.zone_a", _state("on", on_at))
    await tracker._handle_state_change(
        "switch.zone_a", _state("off", on_at + timedelta(minutes=10))
    )

    assert _history(engine) == []


async def test_unknown_entity_ignored(minimal_config: AppConfig, engine) -> None:
    tracker, _ = _make_tracker(minimal_config, engine)
    on_at = datetime(2026, 5, 29, 6, 0, tzinfo=UTC)

    await tracker._handle_state_change("switch.living_room_light", _state("on", on_at))
    await tracker._handle_state_change(
        "switch.living_room_light", _state("off", on_at + timedelta(minutes=5))
    )

    assert _history(engine) == []


async def test_off_without_prior_on_ignored(minimal_config: AppConfig, engine) -> None:
    tracker, _ = _make_tracker(minimal_config, engine)
    off_at = datetime(2026, 5, 29, 6, 0, tzinfo=UTC)

    await tracker._handle_state_change("switch.zone_a", _state("off", off_at))

    assert _history(engine) == []


async def test_malformed_on_timestamp_falls_back_to_now(
    minimal_config: AppConfig, engine
) -> None:
    """A missing/garbled on timestamp must not crash; tracking still records a run."""
    tracker, _ = _make_tracker(minimal_config, engine)

    await tracker._handle_state_change("switch.zone_a", {"state": "on", "last_changed": "garbage"})
    await tracker._handle_state_change(
        "switch.zone_a", _state("off", datetime.now(UTC) + timedelta(minutes=1))
    )

    rows = _history(engine)
    assert len(rows) == 1
    assert rows[0].zone_id == "zone_a"
    assert rows[0].duration_min >= 0


async def test_malformed_off_timestamp_falls_back_to_now(
    minimal_config: AppConfig, engine
) -> None:
    tracker, _ = _make_tracker(minimal_config, engine)
    on_at = datetime.now(UTC) - timedelta(minutes=1)

    await tracker._handle_state_change("switch.zone_a", _state("on", on_at))
    await tracker._handle_state_change(
        "switch.zone_a", {"state": "off", "last_changed": "garbage"}
    )

    rows = _history(engine)
    assert len(rows) == 1
    assert rows[0].zone_id == "zone_a"
    assert rows[0].duration_min >= 0
