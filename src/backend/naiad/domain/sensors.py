from naiad.config import AppConfig
from naiad.domain.factors import SensorSnapshot
from naiad.ha_client import HAClient


def read_sensor_snapshot(ha: HAClient, config: AppConfig) -> SensorSnapshot:
    sensors = config.sensors
    unavailable: list[str] = []

    def _float(entity_id: str, default: float = 0.0) -> float:
        val = ha.get_state_value(entity_id)
        if val is None or val in ("unavailable", "unknown", "none"):
            unavailable.append(entity_id)
            return default
        try:
            return float(val)
        except ValueError:
            unavailable.append(entity_id)
            return default

    def _float_or_none(entity_id: str) -> float | None:
        val = ha.get_state_value(entity_id)
        if val is None or val in ("unavailable", "unknown", "none"):
            unavailable.append(entity_id)
            return None
        try:
            return float(val)
        except ValueError:
            unavailable.append(entity_id)
            return None

    def _bool(entity_id: str, *, safe_default: bool = False) -> bool:
        val = ha.get_state_value(entity_id)
        if val is None or val in ("unavailable", "unknown"):
            unavailable.append(entity_id)
            return safe_default
        return val == "on"

    max_temperature_c = _float_or_none(sensors.temperature_max) if sensors.temperature_max else None

    return SensorSnapshot(
        temperature_c=_float_or_none(sensors.temperature),
        max_temperature_c=max_temperature_c,
        season_on=_bool(sensors.season, safe_default=False),
        wind_on=_bool(sensors.wind, safe_default=False),
        precipitation_prob_today=_float(sensors.precipitation_prob_today),
        precipitation_prob_tomorrow=_float(sensors.precipitation_prob_tomorrow),
        precipitation_today_mm=_float(sensors.precipitation_today),
        precipitation_tomorrow_mm=_float(sensors.precipitation_tomorrow),
        unavailable=unavailable,
    )
