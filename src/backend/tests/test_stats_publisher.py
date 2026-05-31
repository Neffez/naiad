import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine

from naiad.config import AppConfig
from naiad.domain.models import RunHistory
from naiad.stats_publisher import StatsPublisher, compute_totals


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


class FakeMQTT:
    """Captures everything published, mimicking paho's publish signature."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bool]] = []

    def publish(
        self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False
    ) -> None:
        self.messages.append((topic, payload, retain))

    def by_topic(self, topic: str) -> str | None:
        for t, payload, _ in self.messages:
            if t == topic:
                return payload
        return None


def _add_run(
    engine,
    zone_id: str,
    liters: float,
    duration_min: float,
    *,
    ended_at: datetime | None = None,
    finalized: bool = True,
) -> None:
    started = ended_at - timedelta(minutes=duration_min) if ended_at else datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            RunHistory(
                zone_id=zone_id,
                sequence_id="seq_1",
                started_at=started,
                ended_at=ended_at if finalized else None,
                duration_min=duration_min if finalized else None,
                liters=liters if finalized else None,
                triggered_by="cron",
            )
        )
        session.commit()


# ── compute_totals ────────────────────────────────────────────────────────────


def test_compute_totals_sums_and_groups(engine) -> None:
    base = datetime(2026, 5, 30, 6, 0, tzinfo=UTC)
    _add_run(engine, "zone_a", 100.0, 20.0, ended_at=base)
    _add_run(engine, "zone_a", 50.0, 10.0, ended_at=base + timedelta(hours=1))
    _add_run(engine, "zone_b", 30.0, 6.0, ended_at=base + timedelta(hours=2))

    with Session(engine) as session:
        totals = compute_totals(session)

    assert totals.total_liters == pytest.approx(180.0)
    assert totals.total_duration_min == pytest.approx(36.0)
    assert totals.per_zone_liters == {"zone_a": pytest.approx(150.0), "zone_b": pytest.approx(30.0)}
    assert totals.per_zone_duration["zone_a"] == pytest.approx(30.0)
    # Last run is the most recently ended one (zone_b). SQLModel stores naive UTC.
    assert totals.last_liters == pytest.approx(30.0)
    assert totals.last_duration_min == pytest.approx(6.0)
    assert totals.last_ended_at == (base + timedelta(hours=2)).replace(tzinfo=None)


def test_compute_totals_ignores_in_flight_rows(engine) -> None:
    _add_run(engine, "zone_a", 100.0, 20.0, ended_at=datetime(2026, 5, 30, 6, 0, tzinfo=UTC))
    _add_run(engine, "zone_a", 0.0, 0.0, finalized=False)  # still running

    with Session(engine) as session:
        totals = compute_totals(session)

    assert totals.total_liters == pytest.approx(100.0)
    # The running row must not become "last run".
    assert totals.last_liters == pytest.approx(100.0)


def test_compute_totals_empty_history(engine) -> None:
    with Session(engine) as session:
        totals = compute_totals(session)
    assert totals.total_liters == 0.0
    assert totals.per_zone_liters == {}
    assert totals.last_liters is None


# ── publishing ──────────────────────────────────────────────────────────────


def _publisher(config: AppConfig, engine) -> tuple[StatsPublisher, FakeMQTT]:
    fake = FakeMQTT()
    pub = StatsPublisher(config, lambda: Session(engine), client=fake)
    return pub, fake


async def test_publish_emits_discovery_and_state(minimal_config: AppConfig, engine) -> None:
    minimal_config.mqtt.enabled = True
    _add_run(engine, "zone_a", 250.0, 30.0, ended_at=datetime(2026, 5, 30, 6, 0, tzinfo=UTC))
    pub, fake = _publisher(minimal_config, engine)

    await pub.publish_all()

    # Discovery for the total water sensor, retained, under the discovery prefix.
    disco = fake.by_topic("homeassistant/sensor/naiad/water_total/config")
    assert disco is not None
    payload = json.loads(disco)
    assert payload["device_class"] == "water"
    assert payload["state_class"] == "total_increasing"
    assert payload["unit_of_measurement"] == "L"
    assert payload["unique_id"] == "naiad_water_total"
    assert payload["state_topic"] == "naiad/water_total/state"

    # Per-zone discovery exists for each configured zone.
    assert fake.by_topic("homeassistant/sensor/naiad/water_zone_a/config") is not None
    assert fake.by_topic("homeassistant/sensor/naiad/runtime_zone_b/config") is not None

    # State values reflect the recorded run.
    assert fake.by_topic("naiad/water_total/state") == "250"
    assert fake.by_topic("naiad/runtime_total/state") == "30"
    assert fake.by_topic("naiad/water_zone_a/state") == "250"
    assert fake.by_topic("naiad/water_zone_b/state") == "0"
    assert fake.by_topic("naiad/last_run_liters/state") == "250"

    # Everything is published retained.
    assert all(retain for _, _, retain in fake.messages)


async def test_publish_is_noop_when_disconnected(minimal_config: AppConfig, engine) -> None:
    pub, fake = _publisher(minimal_config, engine)
    pub._connected = False

    await pub.publish_all()

    assert fake.messages == []


async def test_disabled_start_does_not_connect(minimal_config: AppConfig, engine) -> None:
    # No client injected and disabled config → start() must not attempt a dial.
    minimal_config.mqtt.enabled = False
    pub = StatsPublisher(minimal_config, lambda: Session(engine))

    await pub.start()

    assert pub._client is None


async def test_on_run_recorded_publishes(minimal_config: AppConfig, engine) -> None:
    minimal_config.mqtt.enabled = True
    pub, fake = _publisher(minimal_config, engine)
    _add_run(engine, "zone_a", 10.0, 2.0, ended_at=datetime(2026, 5, 30, 6, 0, tzinfo=UTC))

    await pub.on_run_recorded()

    assert fake.by_topic("naiad/water_total/state") == "10"
