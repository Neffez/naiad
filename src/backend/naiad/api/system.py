from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, func, select

from naiad.api.schemas import (
    FactorBreakdownResponse,
    MasterToggleRequest,
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
from naiad.timeutil import local_day_start_utc, local_week_start_utc

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


def _week_series(session: Session, tz_name: str) -> list[float]:
    """Liters per local weekday (Mon..Sun) for the current local week."""
    tz = ZoneInfo(tz_name)
    monday_utc = local_week_start_utc(tz_name)

    rows = session.exec(
        select(RunHistory.started_at, RunHistory.liters).where(RunHistory.started_at >= monday_utc)
    ).all()

    buckets = [0.0] * 7
    for started_at, liters in rows:
        if liters is None:
            continue
        local = started_at.replace(tzinfo=UTC).astimezone(tz)
        buckets[local.weekday()] += liters
    return [round(b, 1) for b in buckets]


def _liters_since(session: Session, since: datetime) -> float:
    result = session.exec(
        select(func.sum(RunHistory.liters)).where(RunHistory.started_at >= since)
    ).first()
    return float(result or 0.0)


def _next_plans(session: Session, config: AppConfig, limit: int) -> list[NextRunResponse]:
    now = datetime.now(UTC)
    plans = session.exec(
        select(Plan).where(Plan.scheduled_at >= now).order_by(col(Plan.scheduled_at)).limit(limit)
    ).all()
    result = []
    for p in plans:
        seq_cfg = config.sequences.get(p.sequence_id)
        if seq_cfg is None:
            continue
        basis = p.duration_min if p.duration_min is not None else int(seq_cfg.basis_min_per_zone)
        result.append(
            NextRunResponse(
                sequence_id=p.sequence_id,
                sequence_label=seq_cfg.label,
                scheduled_at=p.scheduled_at,
                duration_min=basis,
            )
        )
    return result[:limit]


@router.get("/status", response_model=SystemStatusResponse)
async def get_status(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
) -> SystemStatusResponse:
    snapshot = read_sensor_snapshot(ha, config)
    factors = compute_factors(snapshot, config, session)

    wind_blocking = [
        seq_id for seq_id, seq in config.sequences.items() if seq.wind_blocks and snapshot.wind_on
    ]

    # RunHistory.started_at is stored as naive UTC; bucket by *local* calendar day
    # and *local* calendar week (Mon→Sun) so "today"/"this week" reset at local
    # midnight and liters_week matches the sum of week_series shown in the chart.
    today_start = local_day_start_utc(config.timezone)
    week_start = local_week_start_utc(config.timezone)

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
        week_series=_week_series(session, config.timezone),
    )


@router.patch("/status/master")
async def set_master(
    body: MasterToggleRequest,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    _set_master(session, body.on)
    return {"master_on": body.on}


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

        result.append(
            ValveStateResponse(
                id=zone.switch,
                zone_id=zone_id,
                label=zone.label,
                state=state,
                on_since=on_since,
                runtime_min=runtime_min,
            )
        )
    return result
