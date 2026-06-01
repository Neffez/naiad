from naiad.config import ZoneConfig
from naiad.ha_client import HAClient


class HAEntityDriver:
    def __init__(self, ha: HAClient) -> None:
        self._ha = ha

    async def turn_on(self, zone: ZoneConfig) -> None:
        await self._ha.call_service("switch", "turn_on", entity_id=zone.switch)

    async def turn_off(self, zone: ZoneConfig) -> None:
        await self._ha.call_service("switch", "turn_off", entity_id=zone.switch)
