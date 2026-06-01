from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from naiad.api.schemas import (
    FactorBreakdownResponse,
    MasterToggleRequest,
    NextRunResponse,
    SkipRunRequest,
    SystemStatusResponse,
    ValveStateResponse,
    WeatherSummaryResponse,
)
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import (
    get_config,
    get_ha_client,
    get_runner,
    get_scheduler,
    require_auth,
)
from naiad.domain.factors import compute_factors
from naiad.domain.models import Plan, RunHistory, SequenceOverride, SkippedRun, UserPreference
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import SequenceRunner, zone_run_id
from naiad.ha_client import HAClient
from naiad.scheduler import next_run_for_sequence, upcoming_cron_runs
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


def _plan_next_run(
    plan: Plan,
    session: Session,
    config: AppConfig,
    with_plan_id: bool = False,
) -> NextRunResponse | None:
    """Build a NextRunResponse for a one-off plan (sequence or single zone), or
    None if its target no longer exists."""
    plan_id = plan.id if with_plan_id else None
    if plan.zone_id is not None:
        zone = config.zones.get(plan.zone_id)
        if zone is None:
            return None
        return NextRunResponse(
            sequence_id=plan.zone_id,
            sequence_label=zone.label,
            scheduled_at=plan.scheduled_at,
            duration_min=plan.duration_min if plan.duration_min is not None else 0,
            plan_id=plan_id,
        )
    seq_cfg = config.sequences.get(plan.sequence_id)
    if seq_cfg is None:
        return None
    duration = (
        plan.duration_min
        if plan.duration_min is not None
        else _effective_basis(session, config, plan.sequence_id)
    )
    return NextRunResponse(
        sequence_id=plan.sequence_id,
        sequence_label=seq_cfg.label,
        scheduled_at=plan.scheduled_at,
        duration_min=duration,
        plan_id=plan_id,
    )


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
        run = _plan_next_run(p, session, config)
        if run is None:
            continue
        when = p.scheduled_at if p.scheduled_at.tzinfo else p.scheduled_at.replace(tzinfo=UTC)
        candidates.append((when, run))

    for seq_id, seq_cfg in config.sequences.items():
        if not seq_cfg.enabled:
            continue
        nxt: datetime | None = next_run_for_sequence(scheduler, seq_id)
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


def _upcoming_day_runs(
    session: Session,
    config: AppConfig,
    scheduler: AsyncIOScheduler,
) -> list[NextRunResponse]:
    """Upcoming (not-yet-started) runs: today's remaining runs plus all runs of
    the next future day that has any (local calendar days).

    Returns today's remaining runs (if any) followed by every run of the earliest
    later day that has scheduled runs — at most two calendar days, or just the next
    day when nothing remains today. Both one-off plans and recurring cron schedules
    are merged and user-skipped cron occurrences are excluded. Currently-running
    runs are *not* included here; they are surfaced live on the sequence/zone cards.
    """
    tz = ZoneInfo(config.timezone)
    now = datetime.now(UTC)
    until = now + timedelta(days=8)
    today = now.astimezone(tz).date()

    # User-skipped cron occurrences, keyed by sequence → set of minute-truncated
    # naive-UTC fire times.
    skip_set: dict[str, set[datetime]] = {}
    for s in session.exec(select(SkippedRun)).all():
        skip_set.setdefault(s.sequence_id, set()).add(
            s.scheduled_at.replace(second=0, microsecond=0)
        )

    candidates: list[tuple[datetime, NextRunResponse]] = []

    plans = session.exec(select(Plan).where(Plan.scheduled_at >= now.replace(tzinfo=None))).all()
    for p in plans:
        run = _plan_next_run(p, session, config, with_plan_id=True)
        if run is None:
            continue
        when = p.scheduled_at if p.scheduled_at.tzinfo else p.scheduled_at.replace(tzinfo=UTC)
        candidates.append((when, run))

    for seq_id, seq_cfg in config.sequences.items():
        if not seq_cfg.enabled:
            continue
        skipped = skip_set.get(seq_id, set())
        for fire in upcoming_cron_runs(scheduler, seq_id, until):
            fire_utc = fire.astimezone(UTC)
            naive_min = fire_utc.replace(tzinfo=None, second=0, microsecond=0)
            if naive_min in skipped:
                continue
            candidates.append(
                (
                    fire_utc,
                    NextRunResponse(
                        sequence_id=seq_id,
                        sequence_label=seq_cfg.label,
                        scheduled_at=naive_min,
                        duration_min=_effective_basis(session, config, seq_id),
                    ),
                )
            )

    if not candidates:
        return []

    candidates.sort(key=lambda c: c[0])

    # All candidates fire at or after "now", so each lands on today or a later day.
    today_runs = [run for when, run in candidates if when.astimezone(tz).date() == today]
    later = [(when, run) for when, run in candidates if when.astimezone(tz).date() > today]
    next_day_runs: list[NextRunResponse] = []
    if later:
        next_date = later[0][0].astimezone(tz).date()
        next_day_runs = [run for when, run in later if when.astimezone(tz).date() == next_date]

    return today_runs + next_day_runs


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

    upcoming_runs = _upcoming_day_runs(session, config, scheduler)
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
            manual=factors.manual,
            wind_blocking_sequences=wind_blocking,
            temp_input_c=(
                snapshot.max_temperature_c
                if snapshot.max_temperature_c is not None
                else snapshot.temperature_c
            ),
            rain_prob_pct=max(
                snapshot.precipitation_prob_today,
                snapshot.precipitation_prob_tomorrow,
            ),
            rain_mm=max(
                snapshot.precipitation_today_mm,
                snapshot.precipitation_tomorrow_mm * config.factors.rain.forecast_decay,
            ),
        ),
        next_run=next_runs[0] if len(next_runs) > 0 else None,
        after_next=next_runs[1] if len(next_runs) > 1 else None,
        upcoming_runs=upcoming_runs,
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


@router.post("/status/skip-run")
async def skip_run(
    body: SkipRunRequest,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Skip a single upcoming run. A one-off plan is deleted; a recurring cron
    occurrence is recorded as skipped so only that fire is suppressed."""
    # A one-off plan (sequence or single zone) is identified by plan_id and
    # deleted directly — no need to resolve the sequence (zone plans have none).
    if body.plan_id is not None:
        plan = session.get(Plan, body.plan_id)
        if plan is not None:
            session.delete(plan)
            session.commit()
        return {"skipped": "plan"}

    if body.sequence_id not in config.sequences:
        raise HTTPException(404, f"Sequence '{body.sequence_id}' not found")

    # Recurring cron occurrence — store its fire time as naive UTC (minute precision)
    # to match how the scheduler compares it when the job fires.
    sched = body.scheduled_at
    if sched.tzinfo is not None:
        sched = sched.astimezone(UTC).replace(tzinfo=None)
    sched = sched.replace(second=0, microsecond=0)
    session.add(SkippedRun(sequence_id=body.sequence_id, scheduled_at=sched))
    session.commit()
    return {"skipped": "occurrence"}


@router.get("/valves", response_model=list[ValveStateResponse])
async def list_valves(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
    runner: SequenceRunner = Depends(get_runner),
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

        # For a standalone single-zone run, expose its planned duration so the UI
        # can show remaining time (e.g. "5 / 10 min").
        zone_run = runner.find_zone_run(zone_id)
        single_run = zone_run is not None and zone_run[0] == zone_run_id(zone_id)
        total_min: float | None = None
        if single_run and zone_run is not None:
            total_min = zone_run[1].duration_min

        result.append(
            ValveStateResponse(
                id=zone.switch,
                zone_id=zone_id,
                label=zone.label,
                state=state,
                on_since=on_since,
                runtime_min=runtime_min,
                total_min=total_min,
                single_run=single_run,
            )
        )
    return result
