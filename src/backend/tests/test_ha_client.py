from naiad.ha_client import HAClient


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
