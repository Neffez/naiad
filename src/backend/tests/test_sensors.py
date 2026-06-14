from naiad.config import AppConfig
from naiad.domain.sensors import read_sensor_snapshot


class FakeHA:
    def __init__(
        self,
        states: dict[str, str],
        daily_max: dict[str, float | None] | None = None,
        confirmed_peak: dict[str, float | None] | None = None,
    ):
        self._states = states
        self._daily_max = daily_max or {}
        self._confirmed_peak = confirmed_peak or {}

    def get_state_value(self, entity_id: str) -> str | None:
        return self._states.get(entity_id)

    def get_cached_daily_max(self, entity_id: str) -> float | None:
        return self._daily_max.get(entity_id)

    def get_rain_confirmed_peak(self, entity_id: str) -> float | None:
        return self._confirmed_peak.get(entity_id)

    def get_et0_balance(self) -> float | None:
        return None

    def get_et0_zonal_aggregate(self) -> float | None:
        return None


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


def test_precipitation_uses_daily_peak_over_current(minimal_config: AppConfig) -> None:
    """The rain forecast scales to the day's peak: an evening drop to 10mm must not
    override a noon peak of 35mm that had stopped irrigation."""
    states = _base_states()
    states["sensor.prec_today"] = "10"  # current (evening) reading dropped back
    states["sensor.prec_prob_today"] = "40"
    ha = FakeHA(
        states,
        daily_max={
            "sensor.prec_today": 35.0,  # the noon peak, from the recorder
            "sensor.prec_prob_today": 90.0,
        },
    )
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.precipitation_today_mm == 35.0
    assert snap.precipitation_prob_today == 90.0


def test_precipitation_carries_rain_confirmed_peak(minimal_config: AppConfig) -> None:
    """The snapshot exposes the rain-confirmed peak per today sensor (current,
    unconfirmed peak, and the peak that coincided with actual rain) so the rain factor
    can confirm today's peak against the rain sensor."""
    states = _base_states()
    states["sensor.prec_today"] = "10"
    ha = FakeHA(
        states,
        daily_max={"sensor.prec_today": 35.0},
        confirmed_peak={"sensor.prec_today": 5.0, "sensor.prec_prob_today": 80.0},
    )
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.precipitation_today_mm == 35.0  # unconfirmed peak
    assert snap.precipitation_today_mm_current == 10.0  # latest reading
    assert snap.precipitation_today_mm_confirmed == 5.0  # peak during real rain
    assert snap.precipitation_prob_today_confirmed == 80.0


def test_precipitation_keeps_current_when_higher_than_peak(minimal_config: AppConfig) -> None:
    """A live reading above the cached peak still wins — the cache never holds the
    forecast back below the latest value."""
    states = _base_states()
    states["sensor.prec_today"] = "40"
    ha = FakeHA(states, daily_max={"sensor.prec_today": 35.0})
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.precipitation_today_mm == 40.0


def test_precipitation_falls_back_to_current_without_cache(minimal_config: AppConfig) -> None:
    states = _base_states()
    states["sensor.prec_today"] = "12"
    ha = FakeHA(states, daily_max={})
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.precipitation_today_mm == 12.0


def test_tomorrow_keeps_live_value_and_separate_peak(minimal_config: AppConfig) -> None:
    """Tomorrow's main field stays the latest reading; the peak (highest seen today)
    is exposed separately so compute_factors can opt into it per peak_tomorrow."""
    states = _base_states()
    states["sensor.prec_tomorrow"] = "10"
    states["sensor.prec_prob_tomorrow"] = "30"
    ha = FakeHA(
        states,
        daily_max={"sensor.prec_tomorrow": 40.0, "sensor.prec_prob_tomorrow": 80.0},
    )
    snap = read_sensor_snapshot(ha, minimal_config)  # type: ignore[arg-type]
    assert snap.precipitation_tomorrow_mm == 10.0  # latest reading
    assert snap.precipitation_tomorrow_mm_peak == 40.0  # day's peak
    assert snap.precipitation_prob_tomorrow == 30.0
    assert snap.precipitation_prob_tomorrow_peak == 80.0
