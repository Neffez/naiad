import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine

from naiad.config import AppConfig
from naiad.domain.models import FactorOverride, RunHistory
from naiad.domain.preferences import read_master_on, set_master_on
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

    def publish(self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> None:
        self.messages.append((topic, payload, retain))

    def by_topic(self, topic: str) -> str | None:
        # Most recent first, so command tests observe the state *after* the command.
        for t, payload, _ in reversed(self.messages):
            if t == topic:
                return payload
        return None


class FakeHA:
    def __init__(self) -> None:
        self._states = {
            "binary_sensor.jahreszeit": "on",
            "binary_sensor.windalarm": "off",
            "sensor.temperature": "20",
            "sensor.prec_prob_today": "0",
            "sensor.prec_prob_tomorrow": "0",
            "sensor.prec_today": "0",
            "sensor.prec_tomorrow": "0",
        }

    def get_state_value(self, entity_id: str) -> str | None:
        return self._states.get(entity_id)

    def get_cached_daily_max(self, entity_id: str) -> float | None:
        return None

    def get_rain_confirmed_peak(self, entity_id: str) -> float | None:
        return None

    def get_recent_rain_credit(self, entity_id: str) -> float | None:
        return 10.0 if entity_id == "sensor.actual_rain" else None


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


def _weather_publisher(config: AppConfig, engine) -> tuple[StatsPublisher, FakeMQTT]:
    fake = FakeMQTT()
    pub = StatsPublisher(config, lambda: Session(engine), ha=FakeHA(), client=fake)  # type: ignore[arg-type]
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


async def test_publish_emits_weather_metric_sensors(minimal_config: AppConfig, engine) -> None:
    minimal_config.mqtt.enabled = True
    data = minimal_config.model_dump()
    data["sensors"]["precipitation_actual"] = "sensor.actual_rain"
    data["factors"]["rain"]["mode"] = "water_balance"
    config = AppConfig.model_validate(data)
    pub, fake = _weather_publisher(config, engine)

    await pub.publish_all()

    rain_credit = fake.by_topic("homeassistant/sensor/naiad/rain_credit/config")
    assert rain_credit is not None
    payload = json.loads(rain_credit)
    assert payload["device_class"] == "precipitation"
    assert payload["unit_of_measurement"] == "mm"

    assert fake.by_topic("naiad/rain_credit/state") == "10"
    assert fake.by_topic("naiad/rain_factor/state") == "66.7"
    assert fake.by_topic("naiad/adjustment_factor/state") == "66.7"


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


# ── control entities ──────────────────────────────────────────────────────────


async def test_publish_emits_control_discovery_and_state(minimal_config: AppConfig, engine) -> None:
    minimal_config.mqtt.enabled = True
    pub, fake = _publisher(minimal_config, engine)

    await pub.publish_all()

    master = json.loads(fake.by_topic("homeassistant/switch/naiad/master/config") or "{}")
    assert master["command_topic"] == "naiad/master/set"
    assert master["state_topic"] == "naiad/master/state"
    assert master["unique_id"] == "naiad_master"

    start = json.loads(fake.by_topic("homeassistant/button/naiad/start_seq_1/config") or "{}")
    assert start["command_topic"] == "naiad/start_seq_1/set"
    assert "state_topic" not in start  # buttons are stateless
    assert fake.by_topic("homeassistant/button/naiad/stop_seq_1/config") is not None
    assert fake.by_topic("homeassistant/button/naiad/start_seq_wind/config") is not None

    number = json.loads(fake.by_topic("homeassistant/number/naiad/manual_factor/config") or "{}")
    assert number["command_topic"] == "naiad/manual_factor/set"
    assert number["min"] == 80  # default temperature-factor bounds
    assert number["max"] == 150
    assert number["unit_of_measurement"] == "%"

    assert fake.by_topic("homeassistant/switch/naiad/manual_mode/config") is not None

    # Control states reflect the defaults: master on, automatic mode, neutral factor.
    assert fake.by_topic("naiad/master/state") == "ON"
    assert fake.by_topic("naiad/manual_mode/state") == "OFF"
    assert fake.by_topic("naiad/manual_factor/state") == "100"


async def test_master_command_toggles_master(minimal_config: AppConfig, engine) -> None:
    pub, fake = _publisher(minimal_config, engine)

    await pub.handle_command("naiad/master/set", "OFF")

    with Session(engine) as session:
        assert read_master_on(session) is False
    assert fake.by_topic("naiad/master/state") == "OFF"

    await pub.handle_command("naiad/master/set", "on")  # payload is case-insensitive

    with Session(engine) as session:
        assert read_master_on(session) is True
    assert fake.by_topic("naiad/master/state") == "ON"


async def test_manual_factor_command_clamps_and_persists(minimal_config: AppConfig, engine) -> None:
    pub, fake = _publisher(minimal_config, engine)

    await pub.handle_command("naiad/manual_factor/set", "120")

    with Session(engine) as session:
        override = session.get(FactorOverride, 1)
        assert override is not None and override.manual_pct == 120
    assert fake.by_topic("naiad/manual_factor/state") == "120"

    # Out-of-bounds values are pinned to the temperature-factor limits, exactly
    # like the settings API.
    await pub.handle_command("naiad/manual_factor/set", "999")
    with Session(engine) as session:
        override = session.get(FactorOverride, 1)
        assert override is not None and override.manual_pct == 150


async def test_manual_mode_command_persists_and_republishes(
    minimal_config: AppConfig, engine
) -> None:
    pub, fake = _publisher(minimal_config, engine)

    await pub.handle_command("naiad/manual_mode/set", "ON")

    with Session(engine) as session:
        override = session.get(FactorOverride, 1)
        assert override is not None and override.manual_mode is True
    assert fake.by_topic("naiad/manual_mode/state") == "ON"


async def test_sequence_button_commands_invoke_handler(minimal_config: AppConfig, engine) -> None:
    pub, _fake = _publisher(minimal_config, engine)
    calls: list[tuple[str, str]] = []

    async def handler(sequence_id: str, action: str) -> None:
        calls.append((sequence_id, action))

    pub.on_sequence_command = handler

    await pub.handle_command("naiad/start_seq_1/set", "PRESS")
    await pub.handle_command("naiad/stop_seq_1/set", "PRESS")
    assert calls == [("seq_1", "start"), ("seq_1", "stop")]

    # Unknown sequences and missing handlers are dropped, never raised.
    await pub.handle_command("naiad/start_nope/set", "PRESS")
    assert len(calls) == 2
    pub.on_sequence_command = None
    await pub.handle_command("naiad/start_seq_1/set", "PRESS")
    assert len(calls) == 2


async def test_malformed_commands_are_ignored(minimal_config: AppConfig, engine) -> None:
    pub, _fake = _publisher(minimal_config, engine)

    await pub.handle_command("naiad/manual_factor/set", "not-a-number")
    await pub.handle_command("naiad/master/set", "maybe")
    await pub.handle_command("other/master/set", "ON")  # foreign base topic
    await pub.handle_command("naiad/unknown_object/set", "ON")

    with Session(engine) as session:
        assert session.get(FactorOverride, 1) is None
        assert read_master_on(session) is True  # untouched default


async def test_handler_exception_does_not_propagate(minimal_config: AppConfig, engine) -> None:
    pub, _fake = _publisher(minimal_config, engine)

    async def failing_handler(sequence_id: str, action: str) -> None:
        raise RuntimeError("boom")

    pub.on_sequence_command = failing_handler

    await pub.handle_command("naiad/start_seq_1/set", "PRESS")  # must not raise


async def test_state_publish_reflects_externally_set_master(
    minimal_config: AppConfig, engine
) -> None:
    # Master toggled through the REST API → the next publish mirrors it to MQTT.
    with Session(engine) as session:
        set_master_on(session, False)
    pub, fake = _publisher(minimal_config, engine)

    await pub.publish_all()

    assert fake.by_topic("naiad/master/state") == "OFF"
