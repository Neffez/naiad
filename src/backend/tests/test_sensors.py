from naiad.config import AppConfig
from naiad.domain.sensors import read_sensor_snapshot


class FakeHA:
    def __init__(self, states: dict[str, str], daily_max: dict[str, float | None] | None = None):
        self._states = states
        self._daily_max = daily_max or {}

    def get_state_value(self, entity_id: str) -> str | None:
        return self._states.get(entity_id)

    def get_cached_daily_max(self, entity_id: str) -> float | None:
        return self._daily_max.get(entity_id)


def _base_states() -> dict[str, str]:
    return {
        "binary_sensor.regen": "off",
        "binary_sensor.windalarm": "off",
        "binary_sensor.jahreszeit": "on",
        "sensor.temperature": "12.0",  # cold night-time current temperature
        "sensor.prec_prob_today": "0",
        "sensor.prec_prob_tomorrow": "0",
        "sensor.prec_today": "0",
        "sensor.prec_tomorrow": "0",
    }


def test_uses_yesterday_max_when_no_forecast_sensor(minimal_config: AppConfig) -> None:
    """With no forecast max sensor, the snapshot's max comes from the cached
    yesterday max (the recorder), not the cold current temperature."""
    ha = FakeHA(_base_states(), daily_max={"sensor.temperature": 26.0})
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.temperature_c == 12.0  # current temp still read (for display)
    assert snap.max_temperature_c == 26.0  # factor uses yesterday's max


def test_forecast_sensor_preferred_over_yesterday(minimal_config: AppConfig) -> None:
    data = minimal_config.model_dump()
    data["sensors"]["temperature_max"] = "sensor.forecast_max"
    config = AppConfig.model_validate(data)

    states = _base_states()
    states["sensor.forecast_max"] = "29.0"
    ha = FakeHA(states, daily_max={"sensor.temperature": 26.0})
    snap = read_sensor_snapshot(ha, config)  # type: ignore[arg-type]
    assert snap.max_temperature_c == 29.0  # forecast wins over yesterday's max


def test_falls_back_to_yesterday_when_forecast_unavailable(minimal_config: AppConfig) -> None:
    data = minimal_config.model_dump()
    data["sensors"]["temperature_max"] = "sensor.forecast_max"
    config = AppConfig.model_validate(data)

    states = _base_states()
    states["sensor.forecast_max"] = "unavailable"
    ha = FakeHA(states, daily_max={"sensor.temperature": 26.0})
    snap = read_sensor_snapshot(ha, config)  # type: ignore[arg-type]
    assert snap.max_temperature_c == 26.0


def test_no_max_anywhere_leaves_none(minimal_config: AppConfig) -> None:
    ha = FakeHA(_base_states(), daily_max={})
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.max_temperature_c is None  # compute_factors then uses current temp
