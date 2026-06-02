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
