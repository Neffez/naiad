import pytest
from sqlmodel import Session, SQLModel, create_engine

from naiad.config import AppConfig
from naiad.domain.factors import SensorSnapshot, compute_factors
from naiad.domain.models import FactorOverride


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


def test_max_temperature_preferred_over_current(minimal_config: AppConfig) -> None:
    """When a forecast max temperature is present it drives the factor instead of
    the (cooler, night-time) current temperature."""
    # current 15°C would reduce; max 25°C should raise to +35%.
    result = compute_factors(_snap(temperature_c=15.0, max_temperature_c=25.0), minimal_config)
    assert result.temp_delta_pct == pytest.approx(35.0)
    assert result.factor_pct == pytest.approx(135.0)


def test_falls_back_to_current_when_no_max(minimal_config: AppConfig) -> None:
    result = compute_factors(_snap(temperature_c=25.0, max_temperature_c=None), minimal_config)
    assert result.temp_delta_pct == pytest.approx(35.0)


def test_forecast_tomorrow_with_decay(minimal_config: AppConfig) -> None:
    # forecast_decay=0.5; tomorrow 40mm × 0.5 = 20mm effective → full block with 90% prob
    result = compute_factors(
        _snap(precipitation_prob_tomorrow=90.0, precipitation_tomorrow_mm=40.0),
        minimal_config,
    )
    assert result.rain_factor_pct == pytest.approx(0.0)


@pytest.fixture
def factor_engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_factor_override_temp_basis(minimal_config: AppConfig, factor_engine) -> None:
    """DB override for temp_basis_c shifts the baseline temperature."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, temp_basis_c=25.0))
        session.commit()

    with Session(factor_engine) as session:
        result = compute_factors(_snap(temperature_c=25.0), minimal_config, session)

    assert result.temp_delta_pct == pytest.approx(0.0)
    assert result.factor_pct == pytest.approx(100.0)


def test_factor_override_rain_zero_above(minimal_config: AppConfig, factor_engine) -> None:
    """DB override for rain_zero_above_mm changes the full-block threshold."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, rain_zero_above_mm=10.0))
        session.commit()

    with Session(factor_engine) as session:
        result = compute_factors(
            _snap(precipitation_prob_today=90.0, precipitation_today_mm=12.0),
            minimal_config,
            session,
        )
    assert result.rain_factor_pct == pytest.approx(0.0)


def test_no_factor_override_uses_yaml(minimal_config: AppConfig, factor_engine) -> None:
    """Without DB overrides, YAML config values are used."""
    with Session(factor_engine) as session:
        result = compute_factors(_snap(), minimal_config, session)
    assert result.factor_pct == pytest.approx(100.0)


# ── Manual adjustment override ────────────────────────────────────────────────


def test_manual_mode_overrides_automatic_factor(minimal_config: AppConfig, factor_engine) -> None:
    """With manual_mode on, the automatic temp/rain calculation is bypassed."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, manual_mode=True, manual_pct=120))
        session.commit()

    with Session(factor_engine) as session:
        # A hot day that would normally push the factor up, plus heavy rain that
        # would normally zero it out — neither applies in manual mode.
        result = compute_factors(
            _snap(temperature_c=40.0, precipitation_prob_today=90.0, precipitation_today_mm=25.0),
            minimal_config,
            session,
        )

    assert result.manual is True
    assert result.factor_pct == pytest.approx(120.0)
    assert result.temp_delta_pct == pytest.approx(0.0)
    assert result.rain_factor_pct == pytest.approx(100.0)


def test_manual_mode_clamped_to_temp_bounds(minimal_config: AppConfig, factor_engine) -> None:
    """A manual percentage beyond the temp factor's min/max is clamped."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, manual_mode=True, manual_pct=999))
        session.commit()

    with Session(factor_engine) as session:
        result = compute_factors(_snap(), minimal_config, session)

    # minimal_config temp max_pct = 150
    assert result.factor_pct == pytest.approx(150.0)


def test_manual_mode_off_uses_automatic(minimal_config: AppConfig, factor_engine) -> None:
    """A stored manual_pct is ignored when manual_mode is False."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, manual_mode=False, manual_pct=120))
        session.commit()

    with Session(factor_engine) as session:
        result = compute_factors(_snap(temperature_c=25.0), minimal_config, session)

    assert result.manual is False
    assert result.factor_pct == pytest.approx(135.0)


def test_manual_mode_overrides_season_off(minimal_config: AppConfig, factor_engine) -> None:
    """Manual mode takes precedence even when the season is off."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, manual_mode=True, manual_pct=100))
        session.commit()

    with Session(factor_engine) as session:
        result = compute_factors(_snap(season_on=False), minimal_config, session)

    assert result.manual is True
    assert result.season_off is False
    assert result.factor_pct == pytest.approx(100.0)


# ── Override validation (C-2 regression) ──────────────────────────────────────


def test_merge_factor_config_rejects_inverted_rain_thresholds(
    minimal_config: AppConfig,
) -> None:
    """An override with reduce_above_mm >= zero_above_mm must raise, so the
    settings endpoint can reject it instead of bricking compute_factors."""
    from pydantic import ValidationError

    from naiad.domain.factors import merge_factor_config

    bad = FactorOverride(id=1, rain_reduce_above_mm=30.0, rain_zero_above_mm=20.0)
    with pytest.raises(ValidationError):
        merge_factor_config(minimal_config, bad)


def test_merge_factor_config_rejects_out_of_range_decay(
    minimal_config: AppConfig,
) -> None:
    from pydantic import ValidationError

    from naiad.domain.factors import merge_factor_config

    bad = FactorOverride(id=1, rain_forecast_decay=2.0)
    with pytest.raises(ValidationError):
        merge_factor_config(minimal_config, bad)


def test_merge_factor_config_accepts_valid_override(minimal_config: AppConfig) -> None:
    from naiad.domain.factors import merge_factor_config

    good = FactorOverride(id=1, rain_reduce_above_mm=2.0, rain_zero_above_mm=15.0)
    temp, rain = merge_factor_config(minimal_config, good)
    assert rain.reduce_above_mm == 2.0
    assert rain.zero_above_mm == 15.0


def test_tomorrow_peak_ignored_by_default(minimal_config: AppConfig) -> None:
    """peak_tomorrow defaults off: the live tomorrow reading drives the factor and a
    higher peak seen earlier today is ignored."""
    result = compute_factors(
        _snap(
            precipitation_prob_tomorrow=20.0,
            precipitation_tomorrow_mm=2.0,
            precipitation_prob_tomorrow_peak=90.0,
            precipitation_tomorrow_mm_peak=40.0,
        ),
        minimal_config,
    )
    assert result.rain_factor_pct == pytest.approx(100.0)  # live 2mm/20% → no reduction


def test_tomorrow_peak_used_when_enabled(minimal_config: AppConfig, factor_engine) -> None:
    """With peak_tomorrow on, the day's peak tomorrow forecast drives the factor even
    after the live reading has dropped back."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, rain_peak_tomorrow=True))
        session.commit()
    with Session(factor_engine) as session:
        result = compute_factors(
            _snap(
                precipitation_prob_tomorrow=20.0,
                precipitation_tomorrow_mm=2.0,
                precipitation_prob_tomorrow_peak=90.0,
                precipitation_tomorrow_mm_peak=40.0,
            ),
            minimal_config,
            session,
        )
    # peak 40mm × decay 0.5 = 20mm effective at 90% prob → full block
    assert result.rain_factor_pct == pytest.approx(0.0)


def test_today_always_uses_peak(minimal_config: AppConfig) -> None:
    """Today's peak always drives the factor regardless of peak_tomorrow: the snapshot
    already carries the peak in precipitation_today_mm."""
    result = compute_factors(
        _snap(precipitation_prob_today=90.0, precipitation_today_mm=40.0),
        minimal_config,
    )
    assert result.rain_factor_pct == pytest.approx(0.0)


def _peak_vs_current_snap() -> SensorSnapshot:
    # High peak earlier today (40mm/90%) but the latest reading has dropped back
    # (2mm/20%): the day spiked in the forecast but may never have actually rained.
    return _snap(
        precipitation_prob_today=90.0,
        precipitation_today_mm=40.0,
        precipitation_prob_today_current=20.0,
        precipitation_today_mm_current=2.0,
    )


def test_rain_sensor_gate_off_by_default_uses_peak(minimal_config: AppConfig) -> None:
    """Without the opt-in flag, today keeps using the peak even if it never rained."""
    result = compute_factors(_peak_vs_current_snap(), minimal_config)
    assert result.rain_factor_pct == pytest.approx(0.0)  # peak 40mm → full block


def test_rain_sensor_gate_falls_back_to_current_when_no_rain(
    minimal_config: AppConfig, factor_engine
) -> None:
    """With confirm_with_rain_sensor on and no rain confirmed today, today's peak is
    ignored — the latest reading drives the factor, so a phantom forecast spike does
    not suppress watering."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, rain_confirm_with_sensor=True))
        session.commit()
    with Session(factor_engine) as session:
        result = compute_factors(_peak_vs_current_snap(), minimal_config, session)
    assert result.rain_factor_pct == pytest.approx(100.0)  # current 2mm/20% → no reduction


def test_rain_sensor_gate_uses_peak_when_rain_confirmed(
    minimal_config: AppConfig, factor_engine
) -> None:
    """With the flag on and the rain sensor confirmed today, today's peak applies."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, rain_confirm_with_sensor=True))
        session.commit()
    snap = _peak_vs_current_snap()
    snap.rain_confirmed_today = True
    with Session(factor_engine) as session:
        result = compute_factors(snap, minimal_config, session)
    assert result.rain_factor_pct == pytest.approx(0.0)  # peak 40mm → full block


def test_rain_sensor_gate_current_falls_back_to_peak_when_unset(
    minimal_config: AppConfig, factor_engine
) -> None:
    """If the snapshot omits the current today fields (older snapshot), the gate falls
    back to the peak field rather than treating today as zero rain."""
    with Session(factor_engine) as session:
        session.add(FactorOverride(id=1, rain_confirm_with_sensor=True))
        session.commit()
    # No *_current fields set, rain not confirmed → falls back to the peak values.
    snap = _snap(precipitation_prob_today=90.0, precipitation_today_mm=40.0)
    with Session(factor_engine) as session:
        result = compute_factors(snap, minimal_config, session)
    assert result.rain_factor_pct == pytest.approx(0.0)
