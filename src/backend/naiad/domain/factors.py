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
        ("threshold_prob", "rain_threshold_prob"),
        ("reduce_above_mm", "rain_reduce_above_mm"),
        ("zero_above_mm", "rain_zero_above_mm"),
        ("forecast_decay", "rain_forecast_decay"),
    ]:
        val = getattr(fo, db_attr)
        if val is not None:
            rain_data[field_name] = val
    eff_rain = RainFactorConfig.model_validate(rain_data)

    return eff_temp, eff_rain


def _effective_factor_config(
    config: AppConfig,
    session: Session | None,
) -> tuple[TempFactorConfig, RainFactorConfig]:
    """Merge YAML factor config with DB overrides (if any)."""
    if session is None:
        return config.factors.temp, config.factors.rain

    from naiad.domain.models import FactorOverride

    return merge_factor_config(config, session.get(FactorOverride, 1))


def compute_factors(
    snapshot: SensorSnapshot,
    config: AppConfig,
    session: Session | None = None,
) -> FactorResult:
    eff_temp, eff_rain = _effective_factor_config(config, session)

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
        eff_rain,
    )

    if snapshot.temperature_c is not None:
        temp_multiplier = _compute_temp_factor(snapshot.temperature_c, eff_temp)
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
