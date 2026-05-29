from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class SensorReading:
    entity_id: str
    state: str
    timestamp: datetime
    attributes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IValveDriver(Protocol):
    async def turn_on(self, zone: Any) -> None: ...
    async def turn_off(self, zone: Any) -> None: ...
    def subscribe_state(self, zone: Any, cb: Callable[[bool, datetime], None]) -> None: ...


@runtime_checkable
class ISensorSource(Protocol):
    async def get_state(self, sensor_id: str) -> SensorReading: ...
    def subscribe(self, sensor_id: str, cb: Callable[[SensorReading], None]) -> None: ...
