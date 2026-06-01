from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IValveDriver(Protocol):
    async def turn_on(self, zone: Any) -> None: ...
    async def turn_off(self, zone: Any) -> None: ...
