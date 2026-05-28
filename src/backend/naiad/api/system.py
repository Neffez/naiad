from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from naiad.api.schemas import (
    FactorBreakdownResponse,
    NextRunResponse,
    SystemStatusResponse,
    ValveStateResponse,
    WeatherSummaryResponse,
)
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, get_ha_client, require_auth
from naiad.domain.factors import compute_factors
from naiad.domain.models import Plan, RunHistory, UserPreference
from naiad.domain.sensors import read_sensor_snapshot
from naiad.ha_client import HAClient

router = APIRouter(tags=["system"])


def _get_master(session: Session) -> bool:
    pref = session.get(UserPreference, "master_on")
    return pref is None or pref.value == "1"


def _set_master(session: Session, value: bool) -> None:
    pref = session.get(UserPreference, "master_on")
    if pref is None:
        pref = UserPreference(key="master_on", value="1" if value else "0")
    else:
        pref.value = "1" if value else "0"
    session.add(pref)
    session.commit()


def _liters_since(session: Session, since: datetime) -> float:
    result = session.exec(
        select(func.sum(RunHistory.liters)).where(RunHistory.started_at >= since)
    ).first()
    return float(result or 0.0)


def _next_plans(session: Session, config: AppConfig, limit: int) -> list[NextRunResponse]:
    now = datetime.now(UTC)
    plans = session.exec(
        select(Plan)
        .where(Plan.scheduled_at >= now)
        .order_by(Plan.scheduled_at)
        .limit(limit)
    ).all()
    result = []
    for p in plans:
        seq_cfg = config.sequences.get(p.sequence_id)
        if seq_cfg is None:
            continue
        basis = p.duration_min if p.duration_min is not None else int(seq_cfg.basis_min_per_zone)
        result.append(NextRunResponse(
            sequence_id=p.sequence_id,
            sequence_label=seq_cfg.label,
            scheduled_at=p.scheduled_at,
            duration_min=basis,
        ))
    return result[:limit]


@router.get("/status", response_model=SystemStatusResponse)
async def get_status(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
) -> SystemStatusResponse:
    snapshot = read_sensor_snapshot(ha, config)
    factors = compute_factors(snapshot, config)

    wind_blocking = [
        seq_id
        for seq_id, seq in config.sequences.items()
        if seq.wind_blocks and snapshot.wind_on
    ]

    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    week_start = now - timedelta(days=7)

    next_runs = _next_plans(session, config, 2)

    return SystemStatusResponse(
        master_on=_get_master(session),
        ha_connected=ha.is_connected,
        weather=WeatherSummaryResponse(
            temp_c=snapshot.temperature_c,
            rain_24h_mm=snapshot.precipitation_today_mm,
            wind_label="on" if snapshot.wind_on else "off",
            season_active=snapshot.season_on,
        ),
        today_factor=FactorBreakdownResponse(
            temp_pct=int(round(factors.temp_delta_pct)),
            rain_pct=int(round(factors.rain_factor_pct)),
            combined_pct=int(round(factors.factor_pct)),
            wind_blocking_sequences=wind_blocking,
        ),
        next_run=next_runs[0] if len(next_runs) > 0 else None,
        after_next=next_runs[1] if len(next_runs) > 1 else None,
        liters_today=_liters_since(session, today_start),
        liters_week=_liters_since(session, week_start),
    )


@router.patch("/status/master")
async def set_master(
    body: dict,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> dict:
    if "on" not in body or not isinstance(body["on"], bool):
        raise HTTPException(422, "Body must contain {\"on\": bool}")
    _set_master(session, body["on"])
    return {"master_on": body["on"]}


@router.get("/valves", response_model=list[ValveStateResponse])
async def list_valves(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
) -> list[ValveStateResponse]:
    result = []
    for zone_id, zone in config.zones.items():
        state_dict = ha.get_state(zone.switch)
        if state_dict is None:
            state = "unknown"
            on_since = None
        else:
            raw = state_dict.get("state", "unknown")
            state = raw if raw in ("on", "off") else "unknown"
            on_since = None
            if state == "on":
                raw_ts = state_dict.get("last_changed", "")
                try:
                    on_since = datetime.fromisoformat(raw_ts)
                except (ValueError, TypeError):
                    on_since = None

        runtime_min: float | None = None
        if on_since is not None:
            runtime_min = (datetime.now(UTC) - on_since).total_seconds() / 60.0

        result.append(ValveStateResponse(
            id=zone.switch,
            zone_id=zone_id,
            label=zone.label,
            state=state,
            on_since=on_since,
            runtime_min=runtime_min,
        ))
    return result
