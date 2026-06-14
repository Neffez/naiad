"""Reference evapotranspiration (ET₀) and the soil water balance for the et0 rain mode.

Pure math — no Home Assistant or database access — so everything here is
unit-testable in isolation. ET₀ uses the Hargreaves-Samani equation (FAO-56
eq. 52) with extraterrestrial radiation from latitude and day of year (FAO-56
eq. 21-25): it only needs daily min/max temperatures, which the configured
temperature sensor's recorder history already provides. A configured daily-ET₀
sensor takes precedence over the internal calculation (see
``HAClient.refresh_et0_balance``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Solar constant in MJ m⁻² min⁻¹ (FAO-56 eq. 21).
_SOLAR_CONSTANT = 0.0820
# 1 MJ m⁻² day⁻¹ corresponds to 0.408 mm/day of evaporated water (FAO-56 eq. 20).
_MJ_TO_MM = 0.408


def extraterrestrial_radiation_mm(latitude_deg: float, day_of_year: int) -> float:
    """Daily extraterrestrial radiation Ra in evaporation-equivalent mm/day.

    FAO-56 eq. 21 with the day-of-year terms of eq. 23-25. The sunset hour angle
    is clamped for polar latitudes where the sun never rises or sets.
    """
    phi = math.radians(latitude_deg)
    day_angle = 2.0 * math.pi / 365.0 * day_of_year
    inverse_distance = 1.0 + 0.033 * math.cos(day_angle)
    declination = 0.409 * math.sin(day_angle - 1.39)
    cos_sunset = max(-1.0, min(1.0, -math.tan(phi) * math.tan(declination)))
    sunset_angle = math.acos(cos_sunset)
    ra_mj = (
        (24.0 * 60.0 / math.pi)
        * _SOLAR_CONSTANT
        * inverse_distance
        * (
            sunset_angle * math.sin(phi) * math.sin(declination)
            + math.cos(phi) * math.cos(declination) * math.sin(sunset_angle)
        )
    )
    return max(0.0, ra_mj * _MJ_TO_MM)


def hargreaves_et0_mm(tmin_c: float, tmax_c: float, ra_mm: float) -> float:
    """Daily reference evapotranspiration via Hargreaves-Samani (FAO-56 eq. 52).

    ``ra_mm`` is the extraterrestrial radiation already expressed in mm/day (see
    ``extraterrestrial_radiation_mm``). Negative results (deep winter) clamp to 0.
    """
    tmean = (tmin_c + tmax_c) / 2.0
    spread = max(0.0, tmax_c - tmin_c)
    return max(0.0, 0.0023 * ra_mm * (tmean + 17.8) * math.sqrt(spread))


@dataclass
class BalanceDay:
    """One local day's inputs to the soil water balance, oldest first."""

    rain_mm: float
    # None = ET₀ unknown for this day (no sensor value and no usable temperature
    # history): the balance falls back to the multiplicative decay heuristic of
    # water-balance mode for that day instead of subtracting nothing.
    et0_mm: float | None
    # Water applied by Naiad's own irrigation on this day, in mm (liters / zone
    # area). Fills the reservoir exactly like rain. Only the per-zone et0_zonal
    # mode supplies this; for the global et0 mode it stays 0.
    irrigation_mm: float = 0.0


def day_index(ts: float, day_bounds: list[tuple[float, float]]) -> int | None:
    """Index of the day window (epoch ``[start, end)``) containing ``ts``.

    The last window is closed on the right so a sample timestamped exactly at the
    window end (e.g. an appended live reading at "now", or a run that ends at the
    current instant) still counts toward today. Returns None when ``ts`` falls
    outside every window. Shared by the rain and irrigation day-bucketing so the
    two never attribute the same instant to different days.
    """
    last = len(day_bounds) - 1
    for idx, (start, end) in enumerate(day_bounds):
        if start <= ts and (ts < end or (idx == last and ts <= end)):
            return idx
    return None


def soil_balance_mm(days: list[BalanceDay], reservoir_mm: float, fallback_decay: float) -> float:
    """Plant-available water (mm) left from recent rain after ET₀ losses.

    Day-by-day running balance, oldest day first: rain (and any irrigation)
    fills the reservoir (surplus beyond ``reservoir_mm`` — field capacity — runs
    off) and ET₀ drains it (never below 0). The window starts empty, so the
    result is a *recent water* credit, conservative in the same direction as
    water-balance mode's decayed credit; it plugs into the same factor mapping.
    """
    balance = 0.0
    for day in days:
        income = max(0.0, day.rain_mm) + max(0.0, day.irrigation_mm)
        balance = min(reservoir_mm, balance + income)
        if day.et0_mm is not None:
            balance = max(0.0, balance - day.et0_mm)
        else:
            balance *= fallback_decay
    return balance


# Plant-available water capacity per soil type, in mm of water per mm of root
# depth (i.e. dimensionless: (field capacity − wilting point) volumetric water
# content). Standard agronomic mid-range values (FAO-56 table 19): sandy soils
# hold little, clays hold the most.
_AVAILABLE_WATER_FRACTION: dict[str, float] = {
    "sand": 0.10,
    "loam": 0.15,
    "clay": 0.18,
}


@dataclass
class ZoneBalanceInput:
    """Per-zone inputs to the et0_zonal balance refresh.

    ``irrigation_mm`` is aligned to the same day windows as the global rain/ET₀
    history (oldest first); ``crop_coefficient`` scales reference ET₀ into the
    zone's actual ETc; ``reservoir_mm`` is the zone's field-capacity cap.
    """

    zone_id: str
    reservoir_mm: float
    crop_coefficient: float
    irrigation_mm: list[float]


def reservoir_from_soil(soil_type: str, root_depth_mm: float, depletion_fraction: float) -> float:
    """Plant-available soil reservoir (mm) the et0_zonal mode drains and refills.

    The total available water in the root zone is ``AWF[soil] × root_depth_mm``;
    only the management-allowed depletion (``depletion_fraction``, the fraction
    that may be used before stress) is treated as the usable reservoir. Unknown
    soil types fall back to loam. The result is clamped to a small positive
    floor so a degenerate config never yields a zero-capacity reservoir.
    """
    awf = _AVAILABLE_WATER_FRACTION.get(soil_type, _AVAILABLE_WATER_FRACTION["loam"])
    total_available = awf * max(0.0, root_depth_mm)
    usable = total_available * max(0.0, min(1.0, depletion_fraction))
    return max(1.0, usable)


def application_rate_mm_per_min(flow_lph: float, area_m2: float) -> float | None:
    """A zone's sprinkler application (precipitation) rate in mm/min.

    ``flow_lph / area_m2`` is the rate in mm/h (1 L/m² = 1 mm), divided by 60 for
    mm/min. Returns None when either input is non-positive — the runtime cannot
    then be derived from a water depth and the caller keeps the factor duration.
    """
    if flow_lph <= 0 or area_m2 <= 0:
        return None
    return flow_lph / area_m2 / 60.0


def deficit_runtime_min(reservoir_mm: float, balance_mm: float, rate_mm_per_min: float) -> float:
    """Minutes of watering to refill the soil reservoir to field capacity.

    The deficit ``reservoir_mm − balance_mm`` (never negative) is the water depth
    to replace; dividing by the zone's application rate gives the runtime. A
    non-positive rate yields 0 (the caller falls back to the factor duration).
    The caller clamps the result to the sequence's configured min/max range.
    """
    if rate_mm_per_min <= 0:
        return 0.0
    deficit = max(0.0, reservoir_mm - balance_mm)
    return deficit / rate_mm_per_min
