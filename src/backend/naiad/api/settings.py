from fastapi import APIRouter, Depends
from sqlmodel import Session, select

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
from naiad.domain.models import FactorOverride, SequenceOverride, UserPreference

router = APIRouter(prefix="/settings", tags=["settings"])

_DEFAULT_TOKEN_LIFETIME = 30


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
    def _r(override_val, default_val):  # type: ignore[no-untyped-def]
        return override_val if (fo and override_val is not None) else default_val

    rain = RainFactorSettingsResponse(
        forecast_days=_r(fo.rain_forecast_days if fo else None, rc.forecast_days),
        threshold_prob=_r(fo.rain_threshold_prob if fo else None, rc.threshold_prob),
        reduce_above_mm=_r(fo.rain_reduce_above_mm if fo else None, rc.reduce_above_mm),
        zero_above_mm=_r(fo.rain_zero_above_mm if fo else None, rc.zero_above_mm),
        forecast_decay=_r(fo.rain_forecast_decay if fo else None, rc.forecast_decay),
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

    auto_login_pref = session.get(UserPreference, "auto_login_enabled")
    auto_login = auto_login_pref.value == "1" if auto_login_pref else False

    return AppSettingsResponse(
        sequences=sequences,
        factors=FactorSettingsResponse(temp=temp, rain=rain),
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
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> AppSettingsResponse:
    from datetime import UTC, datetime

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
        fo.updated_at = datetime.now(UTC)
        session.add(fo)

    if body.sequences is not None:
        for seq_id, override in body.sequences.items():
            if seq_id not in config.sequences:
                continue
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
        pref = (
            session.get(UserPreference, "token_lifetime_days")
            or UserPreference(key="token_lifetime_days", value="")
        )
        pref.value = str(body.token_lifetime_days)
        session.add(pref)

    if body.auto_login_enabled is not None:
        pref = (
            session.get(UserPreference, "auto_login_enabled")
            or UserPreference(key="auto_login_enabled", value="")
        )
        pref.value = "1" if body.auto_login_enabled else "0"
        session.add(pref)

    session.commit()
    return _read_settings(config, session)
