import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from naiad.config import ZoneConfig
from naiad.drivers.protocol import SensorReading
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)


class HAEntityDriver:
    def __init__(self, ha: HAClient) -> None:
        self._ha = ha

    async def turn_on(self, zone: ZoneConfig) -> None:
        await self._ha.call_service("switch", "turn_on", entity_id=zone.switch)

    async def turn_off(self, zone: ZoneConfig) -> None:
        await self._ha.call_service("switch", "turn_off", entity_id=zone.switch)

    def subscribe_state(self, zone: ZoneConfig, cb: Callable[[bool, datetime], None]) -> None:
        entity_id = zone.switch

        async def _handle(eid: str, state: dict[str, Any]) -> None:
            if eid != entity_id:
                return
            is_on = state["state"] == "on"
            raw_ts = state.get("last_changed", "")
            try:
                ts = datetime.fromisoformat(raw_ts)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)
            cb(is_on, ts)

        self._ha.subscribe_state_changes(_handle)


class HAEntitySensorSource:
    def __init__(self, ha: HAClient) -> None:
        self._ha = ha

    async def get_state(self, sensor_id: str) -> SensorReading:
        state = self._ha.get_state(sensor_id)
        if state is None:
            raise ValueError(f"Entity not found in state cache: {sensor_id}")
        raw_ts = state.get("last_changed", "")
        try:
            ts = datetime.fromisoformat(raw_ts)
        except (ValueError, TypeError):
            ts = datetime.now(UTC)
        return SensorReading(
            entity_id=sensor_id,
            state=state["state"],
            timestamp=ts,
            attributes=state.get("attributes", {}),
        )

    def subscribe(self, sensor_id: str, cb: Callable[[SensorReading], None]) -> None:
        async def _handle(eid: str, state: dict[str, Any]) -> None:
            if eid != sensor_id:
                return
            raw_ts = state.get("last_changed", "")
            try:
                ts = datetime.fromisoformat(raw_ts)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)
            cb(
                SensorReading(
                    entity_id=eid,
                    state=state["state"],
                    timestamp=ts,
                    attributes=state.get("attributes", {}),
                )
            )

        self._ha.subscribe_state_changes(_handle)
