from dataclasses import dataclass, field

from naiad.config import AppConfig, RainFactorConfig, TempFactorConfig


@dataclass
class SensorSnapshot:
    temperature_c: float | None
    season_on: bool
    wind_on: bool
    precipitation_prob_today: float
    precipitation_prob_tomorrow: float
    precipitation_today_mm: float
    precipitation_tomorrow_mm: float
    unavailable: list[str] = field(default_factory=list)


@dataclass
class FactorResult:
    factor_pct: float
    temp_delta_pct: float
    rain_factor_pct: float
    wind_on: bool
    season_off: bool
    sensors_unavailable: list[str] = field(default_factory=list)


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


def compute_factors(snapshot: SensorSnapshot, config: AppConfig) -> FactorResult:
    cfg = config.factors

    if not snapshot.season_on:
        return FactorResult(
            factor_pct=0.0,
            temp_delta_pct=0.0,
            rain_factor_pct=100.0,
            wind_on=snapshot.wind_on,
            season_off=True,
            sensors_unavailable=snapshot.unavailable,
        )

    rain_factor = _compute_rain_factor(
        snapshot.precipitation_prob_today,
        snapshot.precipitation_prob_tomorrow,
        snapshot.precipitation_today_mm,
        snapshot.precipitation_tomorrow_mm,
        cfg.rain,
    )

    if snapshot.temperature_c is not None:
        temp_multiplier = _compute_temp_factor(snapshot.temperature_c, cfg.temp)
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
    )
