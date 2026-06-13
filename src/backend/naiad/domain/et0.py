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


def soil_balance_mm(days: list[BalanceDay], reservoir_mm: float, fallback_decay: float) -> float:
    """Plant-available water (mm) left from recent rain after ET₀ losses.

    Day-by-day running balance, oldest day first: rain fills the reservoir
    (surplus beyond ``reservoir_mm`` — field capacity — runs off) and ET₀ drains
    it (never below 0). The window starts empty, so the result is a *recent
    rain* credit, conservative in the same direction as water-balance mode's
    decayed credit; it plugs into the same factor mapping.
    """
    balance = 0.0
    for day in days:
        balance = min(reservoir_mm, balance + max(0.0, day.rain_mm))
        if day.et0_mm is not None:
            balance = max(0.0, balance - day.et0_mm)
        else:
            balance *= fallback_decay
    return balance
