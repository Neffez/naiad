import asyncio
from typing import Any

import pytest

from naiad.ha_client import HAClient, HAError


def test_initial_state() -> None:
    client = HAClient(url="ws://localhost:8123/api/websocket", token="test")
    assert not client.is_connected
    assert client.get_state("sensor.test") is None
    assert client.get_state_value("sensor.test") is None


def test_subscribe_registers_callback() -> None:
    client = HAClient(url="ws://localhost:8123/api/websocket", token="test")

    calls: list[str] = []

    async def cb(entity_id: str, state: dict) -> None:
        calls.append(entity_id)

    client.subscribe_state_changes(cb)
    assert len(client._state_callbacks) == 1


def test_get_services_filters_by_domain() -> None:
    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]  # only needs to be non-None

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        assert msg["type"] == "get_services"
        return {
            "notify": {"mobile_app_a": {}, "notify": {}},
            "light": {"turn_on": {}},
        }

    client._send_command = fake_send  # type: ignore[assignment]
    services = asyncio.run(client.get_services("notify"))
    assert services == ["notify.mobile_app_a", "notify.notify"]


def test_get_services_requires_connection() -> None:
    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    with pytest.raises(HAError):
        asyncio.run(client.get_services())


def test_fetch_history_max_picks_largest_numeric() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        assert msg["type"] == "history/history_during_period"
        return {
            "sensor.temp": [
                {"s": "12.0", "lu": 1.0},
                {"s": "unavailable", "lu": 2.0},  # non-numeric → ignored
                {"s": "27.4", "lu": 3.0},
                {"s": "19.1", "lu": 4.0},
            ]
        }

    client._send_command = fake_send  # type: ignore[assignment]
    start = datetime(2026, 5, 29, tzinfo=UTC)
    end = datetime(2026, 5, 30, tzinfo=UTC)
    result = asyncio.run(client.fetch_history_max("sensor.temp", start, end))
    assert result == pytest.approx(27.4)


def test_refresh_daily_max_caches_value() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return {"sensor.temp": [{"s": "22.5"}]}

    client._send_command = fake_send  # type: ignore[assignment]
    assert client.get_cached_daily_max("sensor.temp") is None
    asyncio.run(
        client.refresh_daily_max(
            "sensor.temp", datetime(2026, 5, 29, tzinfo=UTC), datetime(2026, 5, 30, tzinfo=UTC)
        )
    )
    assert client.get_cached_daily_max("sensor.temp") == pytest.approx(22.5)


def test_refresh_daily_max_swallows_errors() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    # Not connected → fetch raises; refresh must not propagate and leaves cache empty.
    asyncio.run(
        client.refresh_daily_max(
            "sensor.temp", datetime(2026, 5, 29, tzinfo=UTC), datetime(2026, 5, 30, tzinfo=UTC)
        )
    )
    assert client.get_cached_daily_max("sensor.temp") is None


def test_refresh_recent_rain_credit_counts_positive_deltas_and_ignores_resets() -> None:
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        assert msg["type"] == "history/history_during_period"
        return {
            "sensor.rain": [
                {"s": "0", "lu": (now - timedelta(days=2)).timestamp()},
                {"s": "10", "lu": (now - timedelta(days=2, hours=-1)).timestamp()},
                {"s": "0", "lu": (now - timedelta(days=1)).timestamp()},  # daily reset
                {"s": "4", "lu": (now - timedelta(hours=12)).timestamp()},
            ]
        }

    client._state_cache["sensor.rain"] = {"state": "4"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_recent_rain_credit("sensor.rain", now - timedelta(days=3), now, decay=1.0)
    )
    assert client.get_recent_rain_credit("sensor.rain") == pytest.approx(14.0)


def test_refresh_recent_rain_credit_can_require_binary_rain_confirmation() -> None:
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    base = now - timedelta(hours=3)

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": base.timestamp()},
                {"s": "8", "lu": (base + timedelta(hours=1)).timestamp()},
                {"s": "15", "lu": (base + timedelta(hours=2)).timestamp()},
            ]
        },
        "binary_sensor.rain": {
            "binary_sensor.rain": [
                {"s": "off", "lu": base.timestamp()},
                {"s": "on", "lu": (base + timedelta(hours=1, minutes=30)).timestamp()},
            ]
        },
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "15"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_recent_rain_credit(
            "sensor.actual_rain",
            now - timedelta(days=1),
            now,
            decay=1.0,
            rain_entity="binary_sensor.rain",
        )
    )
    assert client.get_recent_rain_credit("sensor.actual_rain") == pytest.approx(7.0)


def test_refresh_recent_rain_credit_with_confirmation_ignores_phantom_forecast() -> None:
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    base = now - timedelta(hours=2)

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": base.timestamp()},
                {"s": "20", "lu": (base + timedelta(hours=1)).timestamp()},
            ]
        },
        "binary_sensor.rain": {"binary_sensor.rain": [{"s": "off", "lu": base.timestamp()}]},
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "20"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_recent_rain_credit(
            "sensor.actual_rain",
            now - timedelta(days=1),
            now,
            decay=1.0,
            rain_entity="binary_sensor.rain",
        )
    )
    assert client.get_recent_rain_credit("sensor.actual_rain") == pytest.approx(0.0)


def _day_bounds(end, num_days):
    """UTC ``[start, end)`` windows for the ``num_days`` local days ending at
    ``end`` (the last window is the partial day up to ``end``)."""
    from datetime import timedelta

    midnight = end.replace(hour=0, minute=0, second=0, microsecond=0)
    bounds = []
    for offset in range(num_days - 1, 0, -1):
        bounds.append((midnight - timedelta(days=offset), midnight - timedelta(days=offset - 1)))
    bounds.append((midnight, end))
    return bounds


def test_refresh_et0_balance_with_et0_sensor() -> None:
    """Rain fills the balance per day; the ET₀ sensor's daily max drains it.
    Today (the last window) only adds rain."""
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    day1 = now - timedelta(days=2)  # full day with rain
    day2 = now - timedelta(days=1)  # full day, dry

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": day1.timestamp()},
                {"s": "10", "lu": (day1 + timedelta(hours=1)).timestamp()},
            ]
        },
        "sensor.et0": {
            "sensor.et0": [
                {"s": "3", "lu": day1.timestamp()},
                {"s": "4", "lu": day2.timestamp()},
                {"s": "5", "lu": now.timestamp()},  # today's value is ignored
            ]
        },
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "10"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_et0_balance(
            day_bounds=_day_bounds(now, 3),
            days_of_year=[152, 153, 154],
            rain_entity="sensor.actual_rain",
            temperature_entity="sensor.temperature",
            et0_entity="sensor.et0",
            reservoir_mm=25.0,
            fallback_decay=0.65,
        )
    )
    # day 1: 0 + 10 - 3 = 7; day 2: 7 - 4 = 3; today: rain only → 3
    assert client.get_et0_balance() == pytest.approx(3.0)


def test_refresh_et0_balance_internal_hargreaves() -> None:
    """Without an ET₀ sensor, daily min/max temperatures + the HA latitude feed
    the internal Hargreaves calculation."""
    from datetime import UTC, datetime, timedelta

    from naiad.domain.et0 import extraterrestrial_radiation_mm, hargreaves_et0_mm

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    client._latitude = 48.0
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    day1 = now - timedelta(days=1)

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": day1.timestamp()},
                {"s": "20", "lu": (day1 + timedelta(hours=2)).timestamp()},
            ]
        },
        "sensor.temperature": {
            "sensor.temperature": [
                {"s": "12", "lu": day1.timestamp()},
                {"s": "26", "lu": (day1 + timedelta(hours=6)).timestamp()},
            ]
        },
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "20"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_et0_balance(
            day_bounds=_day_bounds(now, 2),
            days_of_year=[153, 154],
            rain_entity="sensor.actual_rain",
            temperature_entity="sensor.temperature",
            et0_entity=None,
            reservoir_mm=25.0,
            fallback_decay=0.65,
        )
    )
    expected_et0 = hargreaves_et0_mm(12.0, 26.0, extraterrestrial_radiation_mm(48.0, 153))
    assert client.get_et0_balance() == pytest.approx(20.0 - expected_et0, abs=0.01)


def test_refresh_et0_balance_without_et0_data_decays() -> None:
    """No ET₀ sensor and no latitude → days fall back to the decay heuristic."""
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    day1 = now - timedelta(days=1)

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": day1.timestamp()},
                {"s": "10", "lu": (day1 + timedelta(hours=1)).timestamp()},
            ]
        },
        "sensor.temperature": {"sensor.temperature": []},
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "10"}
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_et0_balance(
            day_bounds=_day_bounds(now, 2),
            days_of_year=[153, 154],
            rain_entity="sensor.actual_rain",
            temperature_entity="sensor.temperature",
            et0_entity=None,
            reservoir_mm=25.0,
            fallback_decay=0.5,
        )
    )
    # day 1: 10 mm rain, ET₀ unknown → × 0.5; today: rain only → 5
    assert client.get_et0_balance() == pytest.approx(5.0)


def test_refresh_et0_balance_counts_rain_since_last_recorder_entry() -> None:
    """The live reading (appended at the window end) still counts toward today —
    rain that fell after the last recorder entry must not be lost."""
    from datetime import UTC, datetime, timedelta

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)

    histories: dict[str, dict[str, list[dict[str, Any]]]] = {
        "sensor.actual_rain": {
            "sensor.actual_rain": [
                {"s": "0", "lu": (now - timedelta(hours=3)).timestamp()},
            ]
        },
        "sensor.temperature": {"sensor.temperature": []},
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return histories[msg["entity_ids"][0]]

    client._state_cache["sensor.actual_rain"] = {"state": "6"}  # rained since
    client._send_command = fake_send  # type: ignore[assignment]
    asyncio.run(
        client.refresh_et0_balance(
            day_bounds=_day_bounds(now, 1),
            days_of_year=[154],
            rain_entity="sensor.actual_rain",
            temperature_entity="sensor.temperature",
            et0_entity=None,
            reservoir_mm=25.0,
            fallback_decay=0.65,
        )
    )
    assert client.get_et0_balance() == pytest.approx(6.0)


def test_refresh_et0_balance_swallows_errors_and_keeps_cache() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._et0_balance_mm = 7.5
    # Not connected → fetch raises; refresh must not propagate nor clobber the cache.
    now = datetime(2026, 6, 3, 12, tzinfo=UTC)
    asyncio.run(
        client.refresh_et0_balance(
            day_bounds=_day_bounds(now, 2),
            days_of_year=[153, 154],
            rain_entity="sensor.actual_rain",
            temperature_entity="sensor.temperature",
            et0_entity=None,
            reservoir_mm=25.0,
            fallback_decay=0.65,
        )
    )
    assert client.get_et0_balance() == pytest.approx(7.5)


def test_max_forecast_during_rain_correlates_peak_timing() -> None:
    """The confirmed peak is the forecast value while rain was on, not the day's max.

    Timeline: forecast 5mm during morning rain (sensor on), then a phantom spike to
    35mm at noon while the sensor is off, then back to 10mm. Only the 5mm coincided
    with real rain."""
    forecast = [(0.0, "5"), (100.0, "35"), (200.0, "10")]
    rain = [(0.0, "off"), (10.0, "on"), (50.0, "off")]
    assert HAClient._max_forecast_during_rain(forecast, rain) == pytest.approx(5.0)


def test_max_forecast_during_rain_constant_forecast_during_rain() -> None:
    """A forecast that does not change during the rain interval is still confirmed."""
    forecast = [(0.0, "5")]  # constant 5mm all day
    rain = [(0.0, "off"), (10.0, "on"), (50.0, "off")]
    assert HAClient._max_forecast_during_rain(forecast, rain) == pytest.approx(5.0)


def test_max_forecast_during_rain_never_rained_returns_zero() -> None:
    """Rain history present but never on → provably unconfirmed → 0.0 (not None)."""
    forecast = [(0.0, "5"), (100.0, "35")]
    rain = [(0.0, "off")]
    assert HAClient._max_forecast_during_rain(forecast, rain) == 0.0


def test_max_forecast_during_rain_no_rain_history_returns_none() -> None:
    """No rain history at all → unknown → None (callers fall back to the peak)."""
    assert HAClient._max_forecast_during_rain([(0.0, "5")], []) is None


def test_max_forecast_during_rain_ignores_unavailable_forecast() -> None:
    """A non-numeric forecast state during rain is skipped, not treated as a value."""
    forecast = [(0.0, "unavailable"), (20.0, "8")]
    rain = [(0.0, "on")]
    assert HAClient._max_forecast_during_rain(forecast, rain) == pytest.approx(8.0)


def test_refresh_rain_confirmed_peak_caches_per_entity() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._connected.set()
    client._ws = object()  # type: ignore[assignment]
    assert client.get_rain_confirmed_peak("sensor.prec_today") is None

    history: dict[str, dict[str, list[dict[str, Any]]]] = {
        "binary_sensor.rain": {
            "binary_sensor.rain": [{"s": "off", "lu": 0.0}, {"s": "on", "lu": 10.0}]
        },
        "sensor.prec_today": {
            "sensor.prec_today": [{"s": "5", "lu": 0.0}, {"s": "35", "lu": 100.0}]
        },
    }

    async def fake_send(ws: Any, msg: dict[str, Any], timeout: float = 10.0) -> Any:
        return history[msg["entity_ids"][0]]

    client._send_command = fake_send  # type: ignore[assignment]
    start, end = datetime(2026, 6, 2, tzinfo=UTC), datetime(2026, 6, 3, tzinfo=UTC)
    asyncio.run(
        client.refresh_rain_confirmed_peak(["sensor.prec_today"], "binary_sensor.rain", start, end)
    )
    # Rain on from t=10 onwards; forecast is 5 then 35 (at t=100, still raining) → 35.
    assert client.get_rain_confirmed_peak("sensor.prec_today") == pytest.approx(35.0)


def test_refresh_rain_confirmed_peak_swallows_errors() -> None:
    from datetime import UTC, datetime

    client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
    client._rain_confirmed_peak_cache["sensor.prec_today"] = 12.0
    # Not connected → fetch raises; refresh must not propagate nor clobber the cache.
    asyncio.run(
        client.refresh_rain_confirmed_peak(
            ["sensor.prec_today"],
            "binary_sensor.rain",
            datetime(2026, 6, 2, tzinfo=UTC),
            datetime(2026, 6, 3, tzinfo=UTC),
        )
    )
    assert client.get_rain_confirmed_peak("sensor.prec_today") == pytest.approx(12.0)


def test_mark_disconnected_cancels_pending_and_fires_offline() -> None:
    """Both close paths route through _mark_disconnected: a clean close (the
    ``async for`` ending normally) must fail pending requests fast and broadcast
    offline, exactly like an abnormal drop — not leave futures hanging."""

    async def run() -> None:
        client = HAClient(url="ws://localhost:8123/api/websocket", token="t")
        client._connected.set()
        client._ws = object()  # type: ignore[assignment]

        offline_calls: list[bool] = []

        async def on_change(connected: bool) -> None:
            offline_calls.append(connected)

        client.on_connection_change = on_change

        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        client._pending[1] = fut

        client._mark_disconnected()

        assert not client.is_connected
        assert client._ws is None
        assert fut.cancelled()
        assert client._pending == {}

        # Let the spawned offline callback run.
        await asyncio.sleep(0)
        assert offline_calls == [False]

        # Idempotent: a second call (e.g. _connect's finally then _connect_loop's
        # except for the same drop) must not re-fire the offline callback.
        client._mark_disconnected()
        await asyncio.sleep(0)
        assert offline_calls == [False]

    asyncio.run(run())


class _FakeWS:
    async def send(self, data: str) -> None:
        pass


def test_send_command_disconnect_surfaces_haerror() -> None:
    """A disconnect while a command is in flight must fail the awaiting caller
    with HAError — catchable by ``except Exception`` retry paths such as
    ``_safe_turn_off`` — instead of leaking the cancelled future's
    CancelledError (a BaseException) into the caller's task."""

    async def run() -> None:
        client = HAClient(url="ws://localhost:8123/api/websocket", token="t")

        async def send_and_expect_error() -> None:
            with pytest.raises(HAError):
                await client._send_command(_FakeWS(), {"type": "call_service"})  # type: ignore[arg-type]

        task = asyncio.create_task(send_and_expect_error())
        await asyncio.sleep(0)  # let the command register its pending future
        assert client._pending  # the command is in flight
        client._mark_disconnected()
        await task

    asyncio.run(run())


def test_send_command_task_cancellation_propagates() -> None:
    """Cancelling the awaiting task itself (process shutdown) must still raise
    CancelledError, so run tasks keep their crash-recovery semantics."""

    async def run() -> None:
        client = HAClient(url="ws://localhost:8123/api/websocket", token="t")

        async def send() -> None:
            await client._send_command(_FakeWS(), {"type": "call_service"})  # type: ignore[arg-type]

        task = asyncio.create_task(send())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
