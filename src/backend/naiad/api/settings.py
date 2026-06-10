import asyncio
from datetime import UTC, datetime
from typing import Literal, TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlmodel import Session, delete, select

from naiad.api.schemas import (
    AppSettingsResponse,
    FactorSettingsResponse,
    RainFactorSettingsResponse,
    SequenceOverrideResponse,
    TempFactorSettingsResponse,
    UpdateSettingsRequest,
)
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.factors import RAIN_OVERRIDE_MAP, TEMP_OVERRIDE_MAP, merge_factor_config
from naiad.domain.models import FactorOverride, SequenceOverride, UserPreference

router = APIRouter(prefix="/settings", tags=["settings"])

_DEFAULT_TOKEN_LIFETIME = 30

_T = TypeVar("_T")

# FactorOverride columns grouped by factor, derived from the single source of
# truth in domain.factors so the "overridden" flags and the reset endpoint can
# never drift from what merge_factor_config actually applies.
_TEMP_OVERRIDE_FIELDS = tuple(db_attr for _, db_attr in TEMP_OVERRIDE_MAP)
_RAIN_OVERRIDE_FIELDS = tuple(db_attr for _, db_attr in RAIN_OVERRIDE_MAP)


def _rain_mode(
    value: str | None, default: Literal["forecast", "water_balance"]
) -> Literal["forecast", "water_balance"]:
    if value in ("forecast", "water_balance"):
        return cast(Literal["forecast", "water_balance"], value)
    return default


# Strong references to fire-and-forget refresh tasks (the event loop only keeps
# weak refs, so without this they could be garbage-collected mid-flight).
_background_tasks: set[asyncio.Task[None]] = set()

# Rain-override columns that feed the cached actual-rain credit. Changing any of
# them warrants an immediate credit recompute instead of waiting for the next
# hourly refresh.
_CREDIT_FIELDS = ("mode", "water_balance_days", "water_balance_decay", "confirm_with_rain_sensor")


def _schedule_rain_credit_refresh(request: Request | None, config: AppConfig) -> None:
    """Recompute the cached actual-rain credit in the background (best-effort).

    The credit is normally refreshed hourly; without this, a changed
    water_balance_days/decay (or the rain-sensor gate) would keep acting on the
    stale cached value for up to an hour. ``request`` is None in direct unit-test
    invocations — then there is no app state (and no HA client) to refresh with.
    """
    if request is None:
        return
    ha = getattr(request.app.state, "ha_client", None)
    session_factory = getattr(request.app.state, "session_factory", None)
    if ha is None or session_factory is None:
        return
    from naiad.scheduler import refresh_recent_rain_credit

    task = asyncio.create_task(
        refresh_recent_rain_credit(config, ha, session_factory),
        name="settings-rain-credit-refresh",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _read_settings(config: AppConfig, session: Session) -> AppSettingsResponse:
    factor_override = session.get(FactorOverride, 1)
    fo = factor_override

    tc = config.factors.temp
    rc = config.factors.rain

    temp = TempFactorSettingsResponse(
        basis_c=fo.temp_basis_c if fo and fo.temp_basis_c is not None else tc.basis_c,
        pct_per_c=fo.temp_pct_per_c if fo and fo.temp_pct_per_c is not None else tc.pct_per_c,
        min_pct=fo.temp_min_pct if fo and fo.temp_min_pct is not None else tc.min_pct,
        max_pct=fo.temp_max_pct if fo and fo.temp_max_pct is not None else tc.max_pct,
    )

    def _r(override_val: _T | None, default_val: _T) -> _T:
        return override_val if (fo and override_val is not None) else default_val

    rain = RainFactorSettingsResponse(
        mode=_rain_mode(fo.rain_mode if fo else None, rc.mode),
        forecast_days=_r(fo.rain_forecast_days if fo else None, rc.forecast_days),
        threshold_prob=_r(fo.rain_threshold_prob if fo else None, rc.threshold_prob),
        reduce_above_mm=_r(fo.rain_reduce_above_mm if fo else None, rc.reduce_above_mm),
        zero_above_mm=_r(fo.rain_zero_above_mm if fo else None, rc.zero_above_mm),
        forecast_decay=_r(fo.rain_forecast_decay if fo else None, rc.forecast_decay),
        water_balance_days=_r(fo.rain_water_balance_days if fo else None, rc.water_balance_days),
        water_balance_decay=_r(fo.rain_water_balance_decay if fo else None, rc.water_balance_decay),
        peak_tomorrow=_r(fo.rain_peak_tomorrow if fo else None, rc.peak_tomorrow),
        confirm_with_rain_sensor=_r(
            fo.rain_confirm_with_sensor if fo else None, rc.confirm_with_rain_sensor
        ),
    )

    overrides = session.exec(select(SequenceOverride)).all()
    seq_map = {o.sequence_id: o for o in overrides}

    sequences: dict[str, SequenceOverrideResponse] = {}
    for seq_id in config.sequences:
        o = seq_map.get(seq_id)
        sequences[seq_id] = SequenceOverrideResponse(
            basis_min_per_zone=o.basis_min_per_zone if o else None,
            watchdog_min=o.watchdog_min if o else None,
            paused=o.paused if o else False,
        )

    lifetime_pref = session.get(UserPreference, "token_lifetime_days")
    lifetime = int(lifetime_pref.value) if lifetime_pref else _DEFAULT_TOKEN_LIFETIME

    # Mirror the effective logic in auth._auto_login_enabled: the DB toggle
    # overrides the YAML default, and the YAML default applies when unset — so the
    # UI reflects the real auto-login state rather than always reporting "off".
    auto_login_pref = session.get(UserPreference, "auto_login_enabled")
    auto_login = auto_login_pref.value == "1" if auto_login_pref else config.auth.auto_login.enabled

    temp_overridden = fo is not None and any(
        getattr(fo, f) is not None for f in _TEMP_OVERRIDE_FIELDS
    )
    rain_overridden = fo is not None and any(
        getattr(fo, f) is not None for f in _RAIN_OVERRIDE_FIELDS
    )

    return AppSettingsResponse(
        sequences=sequences,
        factors=FactorSettingsResponse(
            temp=temp,
            rain=rain,
            manual_mode=fo.manual_mode if fo else False,
            manual_pct=fo.manual_pct if fo else None,
            temp_overridden=temp_overridden,
            rain_overridden=rain_overridden,
        ),
        token_lifetime_days=lifetime,
        auto_login_enabled=auto_login,
    )


@router.get("", response_model=AppSettingsResponse)
async def get_settings(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    return _read_settings(config, session)


@router.patch("", response_model=AppSettingsResponse)
async def update_settings(
    body: UpdateSettingsRequest,
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI; None in unit tests
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    if body.factors is not None:
        fo = session.get(FactorOverride, 1) or FactorOverride(id=1)
        f = body.factors
        if f.temp is not None:
            t = f.temp
            if t.basis_c is not None:
                fo.temp_basis_c = t.basis_c
            if t.pct_per_c is not None:
                fo.temp_pct_per_c = t.pct_per_c
            if t.min_pct is not None:
                fo.temp_min_pct = t.min_pct
            if t.max_pct is not None:
                fo.temp_max_pct = t.max_pct
        if f.rain is not None:
            r = f.rain
            if r.mode is not None:
                fo.rain_mode = r.mode
            if r.forecast_days is not None:
                fo.rain_forecast_days = r.forecast_days
            if r.threshold_prob is not None:
                fo.rain_threshold_prob = r.threshold_prob
            if r.reduce_above_mm is not None:
                fo.rain_reduce_above_mm = r.reduce_above_mm
            if r.zero_above_mm is not None:
                fo.rain_zero_above_mm = r.zero_above_mm
            if r.forecast_decay is not None:
                fo.rain_forecast_decay = r.forecast_decay
            if r.water_balance_days is not None:
                fo.rain_water_balance_days = r.water_balance_days
            if r.water_balance_decay is not None:
                fo.rain_water_balance_decay = r.water_balance_decay
            if r.peak_tomorrow is not None:
                fo.rain_peak_tomorrow = r.peak_tomorrow
            if r.confirm_with_rain_sensor is not None:
                fo.rain_confirm_with_sensor = r.confirm_with_rain_sensor
        # Validate the merged result before persisting: the read path
        # (compute_factors) re-validates and would otherwise raise on every
        # call, bricking status + scheduler. Fail fast with 422 instead.
        try:
            eff_temp, _eff_rain = merge_factor_config(config, fo)
        except ValidationError as e:
            raise HTTPException(422, f"Invalid factor settings: {e}") from e
        if f.manual_mode is not None:
            fo.manual_mode = f.manual_mode
        if f.manual_pct is not None:
            # Clamp to the effective temperature factor bounds: a value beyond the
            # configured min/max is pinned to the nearest limit (see spec).
            fo.manual_pct = max(eff_temp.min_pct, min(eff_temp.max_pct, f.manual_pct))
        fo.updated_at = datetime.now(UTC)
        session.add(fo)

    if body.sequences is not None:
        for seq_id, override in body.sequences.items():
            if seq_id not in config.sequences:
                continue
            if override.basis_min_per_zone is not None and override.basis_min_per_zone <= 0:
                raise HTTPException(422, "basis_min_per_zone must be > 0")
            if override.watchdog_min is not None and override.watchdog_min <= 0:
                raise HTTPException(422, "watchdog_min must be > 0")
            so = session.get(SequenceOverride, seq_id) or SequenceOverride(sequence_id=seq_id)
            if override.basis_min_per_zone is not None:
                so.basis_min_per_zone = override.basis_min_per_zone
            if override.watchdog_min is not None:
                so.watchdog_min = override.watchdog_min
            if override.paused is not None:
                so.paused = override.paused
            so.updated_at = datetime.now(UTC)
            session.add(so)

    if body.token_lifetime_days is not None:
        pref = session.get(UserPreference, "token_lifetime_days") or UserPreference(
            key="token_lifetime_days", value=""
        )
        pref.value = str(body.token_lifetime_days)
        session.add(pref)

    if body.auto_login_enabled is not None:
        pref = session.get(UserPreference, "auto_login_enabled") or UserPreference(
            key="auto_login_enabled", value=""
        )
        pref.value = "1" if body.auto_login_enabled else "0"
        session.add(pref)

    session.commit()

    if body.factors is not None or body.sequences is not None:
        from naiad.api.ws import broadcast_factor_updated

        await broadcast_factor_updated()

    # Keep the MQTT control entities (manual mode/factor) in sync (best-effort).
    if body.factors is not None and request is not None:
        publisher = getattr(request.app.state, "stats_publisher", None)
        if publisher is not None:
            await publisher.publish_all()

    # A changed credit parameter must not act on the stale hourly cache.
    if body.factors is not None and body.factors.rain is not None:
        rain = body.factors.rain
        if any(getattr(rain, field) is not None for field in _CREDIT_FIELDS):
            _schedule_rain_credit_refresh(request, config)

    return _read_settings(config, session)


@router.delete("/factors", response_model=AppSettingsResponse)
async def clear_factor_overrides(
    group: Literal["temp", "rain"] | None = None,
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI; None in unit tests
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    """Clear factor overrides, restoring the configured base values.

    ``group`` limits the reset to the temperature or rain factor; omitting it
    resets both. The PATCH endpoint can only set override fields, never null them,
    so this is the supported way to fall back to the base config. Manual-adjustment
    fields are left untouched — they are a separate concern.
    """
    fo = session.get(FactorOverride, 1)
    if fo is not None:
        fields: list[str] = []
        if group in (None, "temp"):
            fields += _TEMP_OVERRIDE_FIELDS
        if group in (None, "rain"):
            fields += _RAIN_OVERRIDE_FIELDS
        for field in fields:
            setattr(fo, field, None)

        # Drop the row once no overrides remain, so a cleared state is the absence
        # of a row (matching how compute_factors treats a missing override).
        no_overrides = all(
            getattr(fo, f) is None for f in (*_TEMP_OVERRIDE_FIELDS, *_RAIN_OVERRIDE_FIELDS)
        )
        if no_overrides and not fo.manual_mode and fo.manual_pct is None:
            session.delete(fo)
        else:
            fo.updated_at = datetime.now(UTC)
            session.add(fo)
        session.commit()

        from naiad.api.ws import broadcast_factor_updated

        await broadcast_factor_updated()

        # Resetting rain overrides changes the effective credit parameters too.
        if group in (None, "rain"):
            _schedule_rain_credit_refresh(request, config)

    return _read_settings(config, session)


@router.delete("/sequences", response_model=AppSettingsResponse)
async def clear_all_sequence_overrides(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    """Remove all sequence overrides, restoring YAML defaults for every sequence.

    The PATCH endpoint can only set override fields, never null them, so this is
    the supported way to fully reset overrides (e.g. unstick a paused sequence).
    """
    session.exec(delete(SequenceOverride))
    session.commit()

    from naiad.api.ws import broadcast_factor_updated

    await broadcast_factor_updated()

    return _read_settings(config, session)


@router.delete("/sequences/{sequence_id}", response_model=AppSettingsResponse)
async def clear_sequence_override(
    sequence_id: str,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    """Remove the override for a single sequence, restoring its YAML defaults."""
    if sequence_id not in config.sequences:
        raise HTTPException(404, f"Unknown sequence: {sequence_id}")

    override = session.get(SequenceOverride, sequence_id)
    if override is not None:
        session.delete(override)
        session.commit()

        from naiad.api.ws import broadcast_factor_updated

        await broadcast_factor_updated()

    return _read_settings(config, session)
