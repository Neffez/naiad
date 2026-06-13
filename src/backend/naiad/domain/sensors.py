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

    # Temperature used for the adjustment: prefer the forecast daily max; when no
    # forecast sensor is configured (or it's unavailable) fall back to yesterday's
    # recorded max — the current temperature is a poor proxy (cold at night), so it
    # is only the last resort, applied in compute_factors.
    max_temperature_c: float | None = None
    if sensors.temperature_max:
        max_temperature_c = _float_or_none(sensors.temperature_max)
    if max_temperature_c is None:
        max_temperature_c = ha.get_cached_daily_max(sensors.temperature)

    def _peak(entity_id: str, current: float) -> float:
        # The precipitation forecast for the day changes as the day progresses
        # (e.g. 5mm in the morning, 35mm at noon, 10mm in the evening). Using the
        # current reading alone lets an evening drop restart irrigation that the
        # noon peak had correctly stopped. Combine the live value with the day's
        # recorded maximum (kept fresh by the scheduler) so the rain factor can
        # scale to the worst forecast seen today, not just the latest reading.
        cached = ha.get_cached_daily_max(entity_id)
        return current if cached is None else max(current, cached)

    # Today always uses the day's peak. Tomorrow keeps the latest reading plus a
    # separate peak field; compute_factors chooses between them per peak_tomorrow.
    prob_today = _float(sensors.precipitation_prob_today)
    prob_tomorrow = _float(sensors.precipitation_prob_tomorrow)
    mm_today = _float(sensors.precipitation_today)
    mm_tomorrow = _float(sensors.precipitation_tomorrow)

    return SensorSnapshot(
        temperature_c=_float_or_none(sensors.temperature),
        max_temperature_c=max_temperature_c,
        # Optional gate sensors (frost lockout, cistern guard). Unreadable values
        # stay None — the gates never block watering on a broken sensor.
        min_temperature_c=(
            _float_or_none(config.frost.temperature_min) if config.frost.temperature_min else None
        ),
        cistern_level=(
            _float_or_none(config.cistern.level_entity) if config.cistern.level_entity else None
        ),
        season_on=_bool(sensors.season, safe_default=False),
        wind_on=_bool(sensors.wind, safe_default=False),
        precipitation_prob_today=_peak(sensors.precipitation_prob_today, prob_today),
        precipitation_prob_tomorrow=prob_tomorrow,
        precipitation_today_mm=_peak(sensors.precipitation_today, mm_today),
        precipitation_tomorrow_mm=mm_tomorrow,
        precipitation_prob_tomorrow_peak=_peak(sensors.precipitation_prob_tomorrow, prob_tomorrow),
        precipitation_tomorrow_mm_peak=_peak(sensors.precipitation_tomorrow, mm_tomorrow),
        # Latest (non-peak) today readings plus the peak confirmed by actual rain, so
        # the rain factor can confirm today's peak against the rain sensor when
        # confirm_with_rain_sensor is enabled (see rain_factor_inputs).
        precipitation_prob_today_current=prob_today,
        precipitation_today_mm_current=mm_today,
        precipitation_prob_today_confirmed=ha.get_rain_confirmed_peak(
            sensors.precipitation_prob_today
        ),
        precipitation_today_mm_confirmed=ha.get_rain_confirmed_peak(sensors.precipitation_today),
        actual_rain_credit_mm=(
            ha.get_recent_rain_credit(sensors.precipitation_actual)
            if sensors.precipitation_actual
            else None
        ),
        # Only the et0 rain mode refreshes this cache; outside that mode (or
        # before the first refresh) it stays None and the factor ignores it.
        et0_balance_mm=ha.get_et0_balance(),
        unavailable=unavailable,
    )
