"""Publish irrigation statistics to Home Assistant over MQTT discovery.

Naiad tracks every run's liters and duration in its own SQLite ``run_history``.
This module mirrors those figures into Home Assistant as native sensor entities,
using the MQTT-discovery protocol, so that:

* the cumulative liters/duration get long-term statistics in HA, and
* HA's InfluxDB integration forwards the state changes to InfluxDB → Grafana.

The published entities (grouped under one "Naiad" device):

* ``sensor.naiad_water_total``      — cumulative liters (``total_increasing``)
* ``sensor.naiad_water_<zone>``     — cumulative liters per zone
* ``sensor.naiad_runtime_total``    — cumulative run minutes (``total_increasing``)
* ``sensor.naiad_runtime_<zone>``   — cumulative run minutes per zone
* ``sensor.naiad_last_run_liters``  — liters of the most recent run
* ``sensor.naiad_last_run_duration``— minutes of the most recent run
* ``sensor.naiad_last_run``         — timestamp of the most recent run
* ``sensor.naiad_rain_credit``      — recent actual-rain credit in mm
* ``sensor.naiad_rain_factor``      — current rain multiplier in percent
* ``sensor.naiad_adjustment_factor``— current combined watering factor in percent

State and discovery messages are published with ``retain=True`` so the values
survive both Naiad and Home Assistant restarts. The source of truth stays the
SQLite history: every publish recomputes the totals from the database, so it can
never drift from what Naiad recorded.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlmodel import Session, col, func, select

from naiad.config import AppConfig
from naiad.domain.factors import FactorResult, SensorSnapshot, compute_factors
from naiad.domain.models import RunHistory
from naiad.domain.sensors import read_sensor_snapshot
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)


class MQTTClient(Protocol):
    """The subset of the paho-mqtt client surface this module relies on.

    Declared as a Protocol so tests can inject a lightweight fake.
    """

    def publish(
        self, topic: str, payload: Any = ..., qos: int = ..., retain: bool = ...
    ) -> Any: ...


@dataclass
class RunTotals:
    """Aggregated statistics computed from ``run_history``."""

    total_liters: float = 0.0
    total_duration_min: float = 0.0
    per_zone_liters: dict[str, float] = field(default_factory=dict)
    per_zone_duration: dict[str, float] = field(default_factory=dict)
    last_liters: float | None = None
    last_duration_min: float | None = None
    last_ended_at: datetime | None = None


@dataclass(frozen=True)
class WeatherMetrics:
    snapshot: SensorSnapshot
    factors: FactorResult


def compute_totals(session: Session) -> RunTotals:
    """Aggregate liters and run durations from the persisted run history.

    Only finalized runs contribute: rows still in flight have ``liters`` /
    ``duration_min`` set to ``NULL``, which ``SUM`` ignores. The "last run" is the
    most recently *ended* run.
    """
    totals = RunTotals()

    # coalesce(..., 0.0) guarantees a numeric result, but the stubs still type it
    # as float | None — the ``or 0.0`` keeps mypy happy without changing behaviour.
    totals.total_liters = float(
        session.exec(select(func.coalesce(func.sum(RunHistory.liters), 0.0))).one() or 0.0
    )
    totals.total_duration_min = float(
        session.exec(select(func.coalesce(func.sum(RunHistory.duration_min), 0.0))).one() or 0.0
    )

    per_zone = session.exec(
        select(
            RunHistory.zone_id,
            func.coalesce(func.sum(RunHistory.liters), 0.0),
            func.coalesce(func.sum(RunHistory.duration_min), 0.0),
        ).group_by(col(RunHistory.zone_id))
    ).all()
    for zone_id, liters, duration in per_zone:
        totals.per_zone_liters[zone_id] = float(liters or 0.0)
        totals.per_zone_duration[zone_id] = float(duration or 0.0)

    last = session.exec(
        select(RunHistory)
        .where(col(RunHistory.ended_at).is_not(None))
        .order_by(col(RunHistory.ended_at).desc())
    ).first()
    if last is not None:
        totals.last_liters = last.liters
        totals.last_duration_min = last.duration_min
        totals.last_ended_at = last.ended_at

    return totals


@dataclass(frozen=True)
class _EntitySpec:
    """One published sensor: how to advertise it (discovery) and where its state goes."""

    object_id: str  # unique slug, e.g. "water_total" or "water_zone_a"
    name: str
    device_class: str | None
    state_class: str | None
    unit: str | None


class StatsPublisher:
    """Bridges Naiad's run history to Home Assistant MQTT-discovery sensors.

    Connection management (auto-reconnect) is delegated to paho's background
    network loop; paho callbacks run on that loop's thread, so they only schedule
    work back onto the asyncio event loop, where the actual DB reads and publishes
    happen. ``client.publish`` itself is thread-safe, but keeping the DB access on
    the event-loop thread mirrors the rest of the app and avoids cross-thread
    SQLite connection sharing.
    """

    def __init__(
        self,
        config: AppConfig,
        session_factory: Callable[[], Session],
        *,
        ha: HAClient | None = None,
        client: MQTTClient | None = None,
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._ha = ha
        self._client = client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected = client is not None  # injected fakes are "ready" for tests
        self._discovered: set[str] = set()

    # ── Topics ──────────────────────────────────────────────────────────────

    @property
    def _availability_topic(self) -> str:
        return f"{self._config.mqtt.base_topic}/status"

    def _state_topic(self, object_id: str) -> str:
        return f"{self._config.mqtt.base_topic}/{object_id}/state"

    def _discovery_topic(self, object_id: str) -> str:
        return f"{self._config.mqtt.discovery_prefix}/sensor/naiad/{object_id}/config"

    # ── Entity catalogue ──────────────────────────────────────────────────────

    def _entity_specs(self) -> list[_EntitySpec]:
        """The full set of sensors to publish for the current zone configuration."""
        specs: list[_EntitySpec] = [
            _EntitySpec("water_total", "Water total", "water", "total_increasing", "L"),
            _EntitySpec("runtime_total", "Runtime total", "duration", "total_increasing", "min"),
            _EntitySpec("last_run_liters", "Last run liters", "water", "measurement", "L"),
            _EntitySpec("last_run_duration", "Last run duration", "duration", "measurement", "min"),
            _EntitySpec("last_run", "Last run", "timestamp", None, None),
            _EntitySpec("rain_credit", "Rain credit", "precipitation", "measurement", "mm"),
            _EntitySpec("rain_factor", "Rain factor", None, "measurement", "%"),
            _EntitySpec("adjustment_factor", "Adjustment factor", None, "measurement", "%"),
        ]
        for zone_id, zone in self._config.zones.items():
            specs.append(
                _EntitySpec(
                    f"water_{zone_id}",
                    f"Water {zone.label}",
                    "water",
                    "total_increasing",
                    "L",
                )
            )
            specs.append(
                _EntitySpec(
                    f"runtime_{zone_id}",
                    f"Runtime {zone.label}",
                    "duration",
                    "total_increasing",
                    "min",
                )
            )
        return specs

    def _discovery_payload(self, spec: _EntitySpec) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": spec.name,
            "unique_id": f"naiad_{spec.object_id}",
            "object_id": f"naiad_{spec.object_id}",
            "state_topic": self._state_topic(spec.object_id),
            "availability_topic": self._availability_topic,
            "device": {
                "identifiers": ["naiad"],
                "name": "Naiad",
                "manufacturer": "Naiad",
                "model": "Irrigation controller",
            },
        }
        if spec.unit is not None:
            payload["unit_of_measurement"] = spec.unit
        if spec.device_class is not None:
            payload["device_class"] = spec.device_class
        if spec.state_class is not None:
            payload["state_class"] = spec.state_class
        return payload

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to the broker (if enabled) and begin publishing.

        Best-effort: a missing/misconfigured broker is logged and otherwise
        ignored — irrigation never depends on the statistics bridge.
        """
        cfg = self._config.mqtt
        if not cfg.enabled:
            logger.info("MQTT statistics publishing is disabled")
            return
        if not cfg.host:
            logger.warning("MQTT enabled but no broker host configured — not publishing")
            return
        if self._client is not None:
            # A client was injected (tests) — nothing to dial.
            return

        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.warning("paho-mqtt is not installed — MQTT statistics disabled")
            return

        self._loop = asyncio.get_running_loop()
        # paho-mqtt 2.x requires selecting the callback API version. Reference it
        # through an Any alias so the call type-checks regardless of whether the
        # installed paho's type information exposes CallbackAPIVersion (it varies
        # by version: a hard reference errors in one environment or is flagged as
        # an unused ignore in another).
        mqtt_any: Any = mqtt
        client = mqtt.Client(
            mqtt_any.CallbackAPIVersion.VERSION2,
            client_id=cfg.client_id or "naiad",
        )
        if cfg.username:
            client.username_pw_set(cfg.username, cfg.password or None)
        client.will_set(self._availability_topic, "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client = client
        try:
            client.connect_async(cfg.host, cfg.port, keepalive=60)
            client.loop_start()
            logger.info("MQTT statistics bridge connecting to %s:%d", cfg.host, cfg.port)
        except Exception:
            logger.warning(
                "Could not start MQTT bridge to %s:%d", cfg.host, cfg.port, exc_info=True
            )

    async def stop(self) -> None:
        if self._client is None:
            return
        try:
            self._client.publish(self._availability_topic, "offline", retain=True)
            loop_stop = getattr(self._client, "loop_stop", None)
            if loop_stop is not None:
                loop_stop()
            disconnect = getattr(self._client, "disconnect", None)
            if disconnect is not None:
                disconnect()
        except Exception:
            logger.debug("Error while stopping MQTT bridge", exc_info=True)

    # ── paho callbacks (run on paho's network thread) ──────────────────────────

    def _on_connect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None
    ) -> None:
        if getattr(reason_code, "is_failure", reason_code != 0):
            logger.warning("MQTT connect failed: %s", reason_code)
            return
        logger.info("MQTT statistics bridge connected")
        self._connected = True
        client.publish(self._availability_topic, "online", retain=True)
        # Re-advertise discovery on every (re)connect, then push current values.
        self._discovered.clear()
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.publish_all(), self._loop)

    def _on_disconnect(self, *args: Any) -> None:
        self._connected = False
        logger.warning("MQTT statistics bridge disconnected")

    # ── Publishing ──────────────────────────────────────────────────────────

    async def publish_all(self) -> None:
        """Publish discovery (for any not-yet-advertised entities) and current state.

        Awaitable so callers on the event loop (run-finished hook, config reload)
        can simply ``await`` it; the work itself is synchronous and quick.
        """
        if self._client is None or not self._connected:
            return
        try:
            self._publish_discovery()
            self._publish_state()
        except Exception:
            logger.warning("Failed to publish MQTT statistics", exc_info=True)

    def _publish(self, topic: str, payload: str, *, retain: bool = True) -> None:
        assert self._client is not None
        self._client.publish(topic, payload, retain=retain)

    def _publish_discovery(self) -> None:
        for spec in self._entity_specs():
            if spec.object_id in self._discovered:
                continue
            self._publish(
                self._discovery_topic(spec.object_id),
                json.dumps(self._discovery_payload(spec)),
            )
            self._discovered.add(spec.object_id)

    def _publish_state(self) -> None:
        with self._session_factory() as session:
            totals = compute_totals(session)

        self._publish(self._state_topic("water_total"), _num(totals.total_liters))
        self._publish(self._state_topic("runtime_total"), _num(totals.total_duration_min))

        for zone_id in self._config.zones:
            self._publish(
                self._state_topic(f"water_{zone_id}"),
                _num(totals.per_zone_liters.get(zone_id, 0.0)),
            )
            self._publish(
                self._state_topic(f"runtime_{zone_id}"),
                _num(totals.per_zone_duration.get(zone_id, 0.0)),
            )

        if totals.last_liters is not None:
            self._publish(self._state_topic("last_run_liters"), _num(totals.last_liters))
        if totals.last_duration_min is not None:
            self._publish(self._state_topic("last_run_duration"), _num(totals.last_duration_min))
        if totals.last_ended_at is not None:
            self._publish(self._state_topic("last_run"), _isoformat(totals.last_ended_at))
        metrics = self._weather_metrics()
        if metrics is not None:
            self._publish(
                self._state_topic("rain_credit"),
                _num(metrics.snapshot.actual_rain_credit_mm or 0.0),
            )
            self._publish(self._state_topic("rain_factor"), _num(metrics.factors.rain_factor_pct))
            self._publish(self._state_topic("adjustment_factor"), _num(metrics.factors.factor_pct))

    def _weather_metrics(self) -> WeatherMetrics | None:
        if self._ha is None:
            return None
        snapshot = read_sensor_snapshot(self._ha, self._config)
        with self._session_factory() as session:
            factors = compute_factors(snapshot, self._config, session)
        return WeatherMetrics(snapshot=snapshot, factors=factors)

    # ── Hooks ───────────────────────────────────────────────────────────────

    async def on_run_recorded(self) -> None:
        """Callback for the runner/tracker after a run is written to history."""
        await self.publish_all()

    def on_config_changed(self) -> None:
        """Re-advertise discovery (zones may have changed) and refresh state.

        Called from the synchronous config-reload path; schedules the async
        publish on the running event loop.
        """
        self._discovered.clear()
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        loop.create_task(self.publish_all())


def _num(value: float) -> str:
    """Format a numeric state with sensible precision.

    Two decimals max, trailing zeros trimmed, and never scientific notation (which
    ``:g`` would use for large cumulative liters) — HA parses a plain decimal best.
    """
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _isoformat(value: datetime) -> str:
    """ISO 8601 with an explicit UTC offset.

    History timestamps are stored as *naive* UTC (SQLModel strips tzinfo); HA's
    ``timestamp`` device_class needs an offset, so tag naive values as UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
