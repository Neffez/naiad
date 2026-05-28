import pytest

from naiad.config import AppConfig
from naiad.domain.factors import SensorSnapshot, compute_factors


def _snap(**kwargs) -> SensorSnapshot:
    defaults = {
        "temperature_c": 20.0,
        "season_on": True,
        "wind_on": False,
        "precipitation_prob_today": 0.0,
        "precipitation_prob_tomorrow": 0.0,
        "precipitation_today_mm": 0.0,
        "precipitation_tomorrow_mm": 0.0,
    }
    defaults.update(kwargs)
    return SensorSnapshot(**defaults)


def test_no_effect_weather(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(), minimal_config)
    assert result.factor_pct == pytest.approx(100.0)
    assert result.temp_delta_pct == pytest.approx(0.0)
    assert result.rain_factor_pct == pytest.approx(100.0)
    assert not result.season_off
    assert not result.wind_on


def test_temp_above_basis_increases_factor(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(temperature_c=25.0), minimal_config)
    # basis=20, pct_per_c=7 → +35% for +5°C → factor = 1.35
    assert result.temp_delta_pct == pytest.approx(35.0)
    assert result.factor_pct == pytest.approx(135.0)


def test_temp_below_basis_decreases_factor(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(temperature_c=10.0), minimal_config)
    # -10°C → -70% → factor = 0.3, but min_pct=80 clamps to 80
    assert result.factor_pct == pytest.approx(80.0)


def test_temp_max_clamp(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(temperature_c=50.0), minimal_config)
    assert result.factor_pct == pytest.approx(150.0)


def test_rain_below_threshold_prob_no_effect(minimal_config: AppConfig) -> None:
    # threshold_prob=70; 50% prob → no reduction
    snap = _snap(precipitation_prob_today=50.0, precipitation_today_mm=15.0)
    assert compute_factors(snap, minimal_config).rain_factor_pct == pytest.approx(100.0)


def test_rain_below_reduce_above_mm_no_effect(minimal_config: AppConfig) -> None:
    # reduce_above_mm=5; 3mm with 90% prob → no reduction
    snap = _snap(precipitation_prob_today=90.0, precipitation_today_mm=3.0)
    assert compute_factors(snap, minimal_config).rain_factor_pct == pytest.approx(100.0)


def test_rain_partial_reduction(minimal_config: AppConfig) -> None:
    # reduce_above=5, zero_above=20 → 10mm = 1/3 of the way → factor = 1 - (5/15) ≈ 0.667
    result = compute_factors(
        _snap(precipitation_prob_today=90.0, precipitation_today_mm=10.0),
        minimal_config,
    )
    assert result.rain_factor_pct == pytest.approx(100.0 * (1.0 - 5.0 / 15.0), rel=1e-3)


def test_rain_full_block(minimal_config: AppConfig) -> None:
    snap = _snap(precipitation_prob_today=90.0, precipitation_today_mm=25.0)
    result = compute_factors(snap, minimal_config)
    assert result.rain_factor_pct == pytest.approx(0.0)
    assert result.factor_pct == pytest.approx(0.0)


def test_season_off_returns_zero_factor(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(season_on=False), minimal_config)
    assert result.season_off is True
    assert result.factor_pct == pytest.approx(0.0)


def test_wind_on_propagated(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(wind_on=True), minimal_config)
    assert result.wind_on is True


def test_missing_temperature_treated_as_basis(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(temperature_c=None), minimal_config)
    assert result.temp_delta_pct == pytest.approx(0.0)
    assert result.factor_pct == pytest.approx(100.0)


def test_forecast_tomorrow_with_decay(minimal_config: AppConfig) -> None:
    # forecast_decay=0.5; tomorrow 40mm × 0.5 = 20mm effective → full block with 90% prob
    result = compute_factors(
        _snap(precipitation_prob_tomorrow=90.0, precipitation_tomorrow_mm=40.0),
        minimal_config,
    )
    assert result.rain_factor_pct == pytest.approx(0.0)
