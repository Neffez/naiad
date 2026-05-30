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
