import pytest

from naiad.domain.et0 import (
    BalanceDay,
    application_rate_mm_per_min,
    deficit_runtime_min,
    extraterrestrial_radiation_mm,
    hargreaves_et0_mm,
    reservoir_from_soil,
    soil_balance_mm,
)

# 1 MJ m⁻² day⁻¹ ≈ 0.408 mm/day (FAO-56 eq. 20), used to compare against the
# FAO reference values which are stated in MJ.
_MM_PER_MJ = 0.408


def test_extraterrestrial_radiation_matches_fao56_example_8() -> None:
    """FAO-56 Example 8: 20°S on 3 September (day 246) → Ra = 32.2 MJ m⁻² day⁻¹."""
    ra_mm = extraterrestrial_radiation_mm(-20.0, 246)
    assert ra_mm / _MM_PER_MJ == pytest.approx(32.2, abs=0.1)


def test_extraterrestrial_radiation_equator_equinox() -> None:
    """Near the equinox the equator receives its annual maximum (~15.4 mm/day)."""
    assert extraterrestrial_radiation_mm(0.0, 80) == pytest.approx(15.4, abs=0.2)


def test_extraterrestrial_radiation_polar_night_is_zero() -> None:
    """At 80°N in late December the sun never rises — Ra clamps to 0."""
    assert extraterrestrial_radiation_mm(80.0, 355) == pytest.approx(0.0)


def test_hargreaves_matches_fao56_example_20() -> None:
    """FAO-56 Example 20: Lyon (45.72°N) in July, Tmin 14.8 °C / Tmax 26.6 °C
    → ET₀ ≈ 5.0 mm/day."""
    ra_mm = extraterrestrial_radiation_mm(45.72, 196)
    assert hargreaves_et0_mm(14.8, 26.6, ra_mm) == pytest.approx(5.0, abs=0.1)


def test_hargreaves_clamps_negative_to_zero() -> None:
    """Deep-winter temperatures far below -17.8 °C must not yield negative ET₀."""
    assert hargreaves_et0_mm(-30.0, -25.0, 5.0) == 0.0


def test_hargreaves_zero_spread_is_zero() -> None:
    assert hargreaves_et0_mm(20.0, 20.0, 12.0) == 0.0


# ── Soil balance ──────────────────────────────────────────────────────────────


def test_balance_accumulates_rain_minus_et0() -> None:
    days = [BalanceDay(rain_mm=10.0, et0_mm=3.0), BalanceDay(rain_mm=0.0, et0_mm=4.0)]
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.65) == pytest.approx(3.0)


def test_balance_clamps_to_reservoir_capacity() -> None:
    """A downpour beyond field capacity runs off — only the reservoir carries over."""
    days = [BalanceDay(rain_mm=60.0, et0_mm=5.0), BalanceDay(rain_mm=0.0, et0_mm=5.0)]
    # day 1: min(25, 60) - 5 = 20; day 2: 20 - 5 = 15
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.65) == pytest.approx(15.0)


def test_balance_never_negative() -> None:
    days = [BalanceDay(rain_mm=2.0, et0_mm=10.0), BalanceDay(rain_mm=3.0, et0_mm=1.0)]
    # day 1 drains to 0 (not -8); day 2: 0 + 3 - 1 = 2
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.65) == pytest.approx(2.0)


def test_balance_unknown_et0_falls_back_to_decay() -> None:
    """A day without ET₀ data decays multiplicatively (the water-balance heuristic)."""
    days = [BalanceDay(rain_mm=10.0, et0_mm=None)]
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.5) == pytest.approx(5.0)


def test_balance_empty_window_is_zero() -> None:
    assert soil_balance_mm([], reservoir_mm=25.0, fallback_decay=0.65) == 0.0


def test_balance_counts_irrigation_like_rain() -> None:
    """Naiad's own irrigation fills the reservoir just like rain does."""
    days = [BalanceDay(rain_mm=0.0, et0_mm=3.0, irrigation_mm=8.0)]
    # 0 + 8 - 3 = 5
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.65) == pytest.approx(5.0)


def test_balance_rain_plus_irrigation_clamp_to_reservoir() -> None:
    days = [BalanceDay(rain_mm=20.0, et0_mm=0.0, irrigation_mm=20.0)]
    # 20 + 20 capped at 25; no ET₀ loss
    assert soil_balance_mm(days, reservoir_mm=25.0, fallback_decay=0.65) == pytest.approx(25.0)


# ── Reservoir from soil type ────────────────────────────────────────────────


def test_reservoir_from_soil_loam() -> None:
    """Loam (AWF 0.15) over 150 mm roots at 0.5 depletion → 0.15·150·0.5 = 11.25 mm."""
    assert reservoir_from_soil("loam", 150.0, 0.5) == pytest.approx(11.25)


def test_reservoir_from_soil_clay_holds_more_than_sand() -> None:
    clay = reservoir_from_soil("clay", 300.0, 0.5)
    sand = reservoir_from_soil("sand", 300.0, 0.5)
    assert clay > sand


def test_reservoir_unknown_soil_falls_back_to_loam() -> None:
    assert reservoir_from_soil("moon_dust", 150.0, 0.5) == reservoir_from_soil("loam", 150.0, 0.5)


def test_reservoir_has_positive_floor() -> None:
    """A degenerate config never yields a zero-capacity reservoir."""
    assert reservoir_from_soil("sand", 0.0, 0.5) == pytest.approx(1.0)


# ── Deficit-based runtime (stage 3) ─────────────────────────────────────────


def test_application_rate_mm_per_min() -> None:
    """600 L/h over 40 m² = 15 mm/h = 0.25 mm/min."""
    assert application_rate_mm_per_min(600.0, 40.0) == pytest.approx(0.25)


def test_application_rate_none_without_flow_or_area() -> None:
    assert application_rate_mm_per_min(0.0, 40.0) is None
    assert application_rate_mm_per_min(600.0, 0.0) is None


def test_deficit_runtime_refills_to_field_capacity() -> None:
    """A 5 mm deficit at 0.25 mm/min needs 20 minutes."""
    assert deficit_runtime_min(
        reservoir_mm=25.0, balance_mm=20.0, rate_mm_per_min=0.25
    ) == pytest.approx(20.0)


def test_deficit_runtime_zero_when_saturated() -> None:
    """A zone already at or above field capacity needs no watering."""
    assert deficit_runtime_min(reservoir_mm=25.0, balance_mm=30.0, rate_mm_per_min=0.25) == 0.0


def test_deficit_runtime_zero_rate_is_zero() -> None:
    assert deficit_runtime_min(reservoir_mm=25.0, balance_mm=0.0, rate_mm_per_min=0.0) == 0.0
