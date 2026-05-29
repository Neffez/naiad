import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from naiad.config import AppConfig
from naiad.domain.models import RunHistory
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)


class LiterTracker:
    """Records external valve activity (not initiated by SequenceRunner)."""

    def __init__(
        self,
        ha: HAClient,
        config: AppConfig,
        session_factory: Callable[[], Any],
        is_managed: Callable[[str], bool],
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._is_managed = is_managed
        self._on_times: dict[str, datetime] = {}
        self._entity_to_zone: dict[str, str] = {}
        self.rebuild_zone_map()
        ha.subscribe_state_changes(self._handle_state_change)

    def rebuild_zone_map(self) -> None:
        """Rebuild the switch→zone lookup from the (possibly reloaded) config."""
        self._entity_to_zone = {z.switch: z_id for z_id, z in self._config.zones.items()}

    async def _handle_state_change(self, entity_id: str, state: dict[str, Any]) -> None:
        if entity_id not in self._entity_to_zone:
            return

        zone_id = self._entity_to_zone[entity_id]

        if state["state"] == "on":
            raw_ts = state.get("last_changed", "")
            try:
                self._on_times[entity_id] = datetime.fromisoformat(raw_ts)
            except (ValueError, TypeError):
                self._on_times[entity_id] = datetime.now(UTC)

        elif state["state"] == "off" and entity_id in self._on_times:
            on_time = self._on_times.pop(entity_id)

            if self._is_managed(zone_id):
                return  # SequenceRunner handles this entry

            off_raw = state.get("last_changed", "")
            try:
                off_time = datetime.fromisoformat(off_raw)
            except (ValueError, TypeError):
                off_time = datetime.now(UTC)

            duration_min = (off_time - on_time).total_seconds() / 60
            zone_cfg = self._config.zones[zone_id]
            liters = duration_min / 60.0 * zone_cfg.flow_lph

            logger.info(
                "External valve activity: zone=%s %.1f min %.1f L",
                zone_id,
                duration_min,
                liters,
            )

            with self._session_factory() as session:
                session.add(
                    RunHistory(
                        zone_id=zone_id,
                        sequence_id="",
                        started_at=on_time,
                        ended_at=off_time,
                        duration_min=duration_min,
                        liters=liters,
                        triggered_by="external",
                        aborted=False,
                    )
                )
                session.commit()
