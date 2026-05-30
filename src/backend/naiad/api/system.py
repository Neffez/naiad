from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

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
from naiad.dependencies import get_config, get_ha_client, get_scheduler, require_auth
from naiad.domain.factors import compute_factors
from naiad.domain.models import Plan, RunHistory, SequenceOverride, UserPreference
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


def _effective_basis(session: Session, config: AppConfig, seq_id: str) -> int:
    seq_cfg = config.sequences[seq_id]
    override = session.get(SequenceOverride, seq_id)
    if override is not None and override.basis_min_per_zone is not None:
        return int(override.basis_min_per_zone)
    return int(seq_cfg.basis_min_per_zone)


def _next_runs(
    session: Session,
    config: AppConfig,
    scheduler: AsyncIOScheduler,
    limit: int,
) -> list[NextRunResponse]:
    """Upcoming runs from both one-off plans and recurring cron schedules.

    The hero card must surface whichever fires next, so both sources are merged
    and sorted. scheduled_at is kept as naive UTC to match Plan storage; the API
    serializer tags it as UTC on the way out.
    """
    now = datetime.now(UTC)
    candidates: list[tuple[datetime, NextRunResponse]] = []

    plans = session.exec(select(Plan).where(Plan.scheduled_at >= now.replace(tzinfo=None))).all()
    for p in plans:
        seq_cfg = config.sequences.get(p.sequence_id)
        if seq_cfg is None:
            continue
        when = p.scheduled_at if p.scheduled_at.tzinfo else p.scheduled_at.replace(tzinfo=UTC)
        duration = (
            p.duration_min
            if p.duration_min is not None
            else _effective_basis(session, config, p.sequence_id)
        )
        candidates.append(
            (
                when,
                NextRunResponse(
                    sequence_id=p.sequence_id,
                    sequence_label=seq_cfg.label,
                    scheduled_at=p.scheduled_at,
                    duration_min=duration,
                ),
            )
        )

    for seq_id, seq_cfg in config.sequences.items():
        if not seq_cfg.enabled:
            continue
        job = scheduler.get_job(f"cron-{seq_id}")
        nxt: datetime | None = job.next_run_time if job else None
        if nxt is None:
            continue
        candidates.append(
            (
                nxt.astimezone(UTC),
                NextRunResponse(
                    sequence_id=seq_id,
                    sequence_label=seq_cfg.label,
                    scheduled_at=nxt.astimezone(UTC).replace(tzinfo=None),
                    duration_min=_effective_basis(session, config, seq_id),
                ),
            )
        )

    candidates.sort(key=lambda c: c[0])
    return [run for _, run in candidates[:limit]]


@router.get("/status", response_model=SystemStatusResponse)
async def get_status(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
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

    next_runs = _next_runs(session, config, scheduler, 2)

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
            # Both are signed deltas from neutral (0 = no adjustment). temp_delta_pct
            # is already a delta; rain_factor_pct is a multiplier in % (100 = neutral),
            # so subtract 100 to express it as a delta too.
            temp_pct=int(round(factors.temp_delta_pct)),
            rain_pct=int(round(factors.rain_factor_pct)) - 100,
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
