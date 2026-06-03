from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from naiad.config import AppConfig, RainFactorConfig, TempFactorConfig

if TYPE_CHECKING:
    from sqlmodel import Session

    from naiad.domain.models import FactorOverride


@dataclass
class SensorSnapshot:
    temperature_c: float | None
    season_on: bool
    wind_on: bool
    # Today's values are the day's peak forecast (highest seen since local
    # midnight); tomorrow's are the latest reading. The ``*_tomorrow_peak`` fields
    # carry tomorrow's peak so ``compute_factors`` can opt into it via
    # ``RainFactorConfig.peak_tomorrow`` (default off — see ``rain_factor_inputs``).
    precipitation_prob_today: float
    precipitation_prob_tomorrow: float
    precipitation_today_mm: float
    precipitation_tomorrow_mm: float
    # The day's forecast maximum temperature, when a max-temperature sensor is
    # configured. Preferred over ``temperature_c`` for the temperature factor.
    max_temperature_c: float | None = None
    # Tomorrow's peak forecast (highest seen today). None falls back to the latest
    # tomorrow reading, so callers/tests that omit them keep the old behaviour.
    precipitation_prob_tomorrow_peak: float | None = None
    precipitation_tomorrow_mm_peak: float | None = None
    # Today's *latest* (non-peak) reading, used when the peak is gated on the rain
    # sensor (``RainFactorConfig.confirm_with_rain_sensor``). None falls back to the
    # peak field, so callers/tests that omit them keep the old behaviour.
    precipitation_prob_today_current: float | None = None
    precipitation_today_mm_current: float | None = None
    # Today's forecast peak confirmed by actual rain — the max value reached while the
    # binary rain sensor was on (see ``HAClient.get_rain_confirmed_peak``). None = not
    # yet computed (fall back to the unconfirmed peak), 0.0 = it never rained today.
    # Only consulted when ``confirm_with_rain_sensor`` is enabled.
    precipitation_prob_today_confirmed: float | None = None
    precipitation_today_mm_confirmed: float | None = None
    # Recent actual rain retained as a water-balance credit. This is precomputed
    # from HA recorder history by the scheduler/HA client so factor calculation
    # stays synchronous at cron fire time.
    actual_rain_credit_mm: float | None = None
    unavailable: list[str] = field(default_factory=list)


@dataclass
class FactorResult:
    factor_pct: float
    temp_delta_pct: float
    rain_factor_pct: float
    wind_on: bool
    season_off: bool
    sensors_unavailable: list[str] = field(default_factory=list)
    rain_mm: float | None = None
    rain_prob_pct: float | None = None
    # True when factor_pct comes from a manual override rather than the automatic
    # temp/rain calculation. The temp/rain breakdown fields are neutral in that case.
    manual: bool = False


def _compute_temp_factor(temp_c: float, cfg: TempFactorConfig) -> float:
    delta = temp_c - cfg.basis_c
    factor = 1.0 + delta * cfg.pct_per_c / 100.0
    return max(cfg.min_pct / 100.0, min(cfg.max_pct / 100.0, factor))


def _compute_rain_factor(
    prob_today: float,
    prob_tomorrow: float,
    mm_today: float,
    mm_tomorrow: float,
    cfg: RainFactorConfig,
) -> float:
    # forecast_decay discounts tomorrow's mm only — probability is taken at face value
    rain_mm = max(mm_today, mm_tomorrow * cfg.forecast_decay)
    rain_prob = max(prob_today, prob_tomorrow)

    if rain_prob < cfg.threshold_prob or rain_mm < cfg.reduce_above_mm:
        return 1.0
    if rain_mm >= cfg.zero_above_mm:
        return 0.0

    span = cfg.zero_above_mm - cfg.reduce_above_mm
    return 1.0 - (rain_mm - cfg.reduce_above_mm) / span


def _compute_water_balance_rain_factor(
    forecast_prob_today: float,
    forecast_prob_tomorrow: float,
    forecast_mm_today: float,
    forecast_mm_tomorrow: float,
    actual_credit_mm: float,
    cfg: RainFactorConfig,
) -> tuple[float, float, float]:
    forecast_mm = max(forecast_mm_today, forecast_mm_tomorrow * cfg.forecast_decay)
    forecast_prob = max(forecast_prob_today, forecast_prob_tomorrow)
    if forecast_prob < cfg.threshold_prob:
        forecast_mm = 0.0
    effective_mm = max(forecast_mm, actual_credit_mm)
    effective_prob = (
        100.0 if actual_credit_mm >= forecast_mm and actual_credit_mm > 0 else forecast_prob
    )
    if effective_mm < cfg.reduce_above_mm:
        return 1.0, effective_prob, effective_mm
    if effective_mm >= cfg.zero_above_mm:
        return 0.0, effective_prob, effective_mm

    span = cfg.zero_above_mm - cfg.reduce_above_mm
    return 1.0 - (effective_mm - cfg.reduce_above_mm) / span, effective_prob, effective_mm


def _confirmed_today(confirmed: float | None, current: float | None, peak: float) -> float:
    """Today's effective forecast when the rain-sensor confirmation gate is on.

    The live reading always counts; the *sticky* peak above it only counts up to the
    level confirmed by actual rain. ``confirmed`` None means "not computed yet" — fall
    back to the unconfirmed peak (conservative) rather than dropping suppression."""
    if confirmed is None:
        return peak
    cur = current if current is not None else peak
    return max(cur, confirmed)


def rain_factor_inputs(
    snapshot: SensorSnapshot, peak_tomorrow: bool, confirm_with_rain_sensor: bool = False
) -> tuple[float, float, float, float]:
    """The (prob_today, prob_tomorrow, mm_today, mm_tomorrow) values fed to the rain
    factor. Today uses the day's peak forecast; tomorrow uses its peak only when
    ``peak_tomorrow`` is enabled, otherwise the latest reading.

    When ``confirm_with_rain_sensor`` is enabled, today's peak is confirmed against the
    binary rain sensor: today = max(latest reading, the forecast peak that coincided
    with actual rain). A forecast spike that never produced real rain therefore does
    not suppress irrigation, while a peak that *did* rain still counts. Shared by
    ``compute_factors`` and the status endpoint so the displayed rain figures match
    what actually drives the adjustment."""
    if confirm_with_rain_sensor:
        prob_today = _confirmed_today(
            snapshot.precipitation_prob_today_confirmed,
            snapshot.precipitation_prob_today_current,
            snapshot.precipitation_prob_today,
        )
        mm_today = _confirmed_today(
            snapshot.precipitation_today_mm_confirmed,
            snapshot.precipitation_today_mm_current,
            snapshot.precipitation_today_mm,
        )
    else:
        prob_today = snapshot.precipitation_prob_today
        mm_today = snapshot.precipitation_today_mm

    if peak_tomorrow:
        prob_tomorrow = snapshot.precipitation_prob_tomorrow_peak
        if prob_tomorrow is None:
            prob_tomorrow = snapshot.precipitation_prob_tomorrow
        mm_tomorrow = snapshot.precipitation_tomorrow_mm_peak
        if mm_tomorrow is None:
            mm_tomorrow = snapshot.precipitation_tomorrow_mm
    else:
        prob_tomorrow = snapshot.precipitation_prob_tomorrow
        mm_tomorrow = snapshot.precipitation_tomorrow_mm
    return (prob_today, prob_tomorrow, mm_today, mm_tomorrow)


def merge_factor_config(
    config: AppConfig,
    fo: FactorOverride | None,
) -> tuple[TempFactorConfig, RainFactorConfig]:
    """Merge YAML factor config with a FactorOverride row (if any).

    The merged values are run through the pydantic validators, so an override
    that violates a cross-field constraint (e.g. reduce_above_mm >= zero_above_mm)
    raises a ValidationError here.
    """
    temp_cfg = config.factors.temp
    rain_cfg = config.factors.rain

    if fo is None:
        return temp_cfg, rain_cfg

    temp_data = temp_cfg.model_dump()
    for field_name, db_attr in [
        ("basis_c", "temp_basis_c"),
        ("pct_per_c", "temp_pct_per_c"),
        ("min_pct", "temp_min_pct"),
        ("max_pct", "temp_max_pct"),
    ]:
        val = getattr(fo, db_attr)
        if val is not None:
            temp_data[field_name] = val
    eff_temp = TempFactorConfig.model_validate(temp_data)

    rain_data = rain_cfg.model_dump()
    for field_name, db_attr in [
        ("forecast_days", "rain_forecast_days"),
        ("mode", "rain_mode"),
        ("threshold_prob", "rain_threshold_prob"),
        ("reduce_above_mm", "rain_reduce_above_mm"),
        ("zero_above_mm", "rain_zero_above_mm"),
        ("forecast_decay", "rain_forecast_decay"),
        ("water_balance_days", "rain_water_balance_days"),
        ("water_balance_decay", "rain_water_balance_decay"),
        ("peak_tomorrow", "rain_peak_tomorrow"),
        ("confirm_with_rain_sensor", "rain_confirm_with_sensor"),
    ]:
        val = getattr(fo, db_attr)
        if val is not None:
            rain_data[field_name] = val
    eff_rain = RainFactorConfig.model_validate(rain_data)

    return eff_temp, eff_rain


def _clamp_manual_pct(pct: int, eff_temp: TempFactorConfig) -> int:
    """Clamp a manual adjustment percentage to the temperature factor's bounds."""
    return max(eff_temp.min_pct, min(eff_temp.max_pct, pct))


def compute_factors(
    snapshot: SensorSnapshot,
    config: AppConfig,
    session: Session | None = None,
) -> FactorResult:
    override = None
    if session is not None:
        from naiad.domain.models import FactorOverride

        override = session.get(FactorOverride, 1)

    eff_temp, eff_rain = merge_factor_config(config, override)

    # Manual override: bypass the automatic calculation entirely and use the
    # user-set percentage (clamped to the configured bounds) as the combined factor.
    if override is not None and override.manual_mode and override.manual_pct is not None:
        manual = float(_clamp_manual_pct(override.manual_pct, eff_temp))
        return FactorResult(
            factor_pct=manual,
            temp_delta_pct=0.0,
            rain_factor_pct=100.0,
            wind_on=snapshot.wind_on,
            season_off=False,
            sensors_unavailable=snapshot.unavailable,
            manual=True,
        )

    if not snapshot.season_on:
        return FactorResult(
            factor_pct=0.0,
            temp_delta_pct=0.0,
            rain_factor_pct=100.0,
            wind_on=snapshot.wind_on,
            season_off=True,
            sensors_unavailable=snapshot.unavailable,
        )

    prob_today, prob_tomorrow, mm_today, mm_tomorrow = rain_factor_inputs(
        snapshot, eff_rain.peak_tomorrow, eff_rain.confirm_with_rain_sensor
    )
    if eff_rain.mode == "water_balance":
        rain_factor, rain_prob, rain_mm = _compute_water_balance_rain_factor(
            prob_today,
            prob_tomorrow,
            mm_today,
            mm_tomorrow,
            snapshot.actual_rain_credit_mm or 0.0,
            eff_rain,
        )
    else:
        rain_factor = _compute_rain_factor(
            prob_today, prob_tomorrow, mm_today, mm_tomorrow, eff_rain
        )
        rain_prob = max(prob_today, prob_tomorrow)
        rain_mm = max(mm_today, mm_tomorrow * eff_rain.forecast_decay)

    # Prefer the day's forecast maximum so a night-time run still scales to the
    # daytime peak; fall back to the current temperature when no max is available.
    temp_for_factor = (
        snapshot.max_temperature_c
        if snapshot.max_temperature_c is not None
        else snapshot.temperature_c
    )
    if temp_for_factor is not None:
        temp_multiplier = _compute_temp_factor(temp_for_factor, eff_temp)
    else:
        temp_multiplier = 1.0

    combined = max(0.0, min(2.0, temp_multiplier * rain_factor))

    return FactorResult(
        factor_pct=round(combined * 100.0, 1),
        temp_delta_pct=round((temp_multiplier - 1.0) * 100.0, 1),
        rain_factor_pct=round(rain_factor * 100.0, 1),
        wind_on=snapshot.wind_on,
        season_off=False,
        sensors_unavailable=snapshot.unavailable,
        rain_mm=round(rain_mm, 1),
        rain_prob_pct=round(rain_prob, 1),
    )
