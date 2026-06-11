import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from naiad.api.schemas import CreatePlanRequest, NextRunResponse, PlanResponse
from naiad.api.system import upcoming_run_candidates
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, get_scheduler, require_auth
from naiad.domain.models import Plan
from naiad.timeutil import to_naive_utc

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/upcoming", response_model=list[NextRunResponse])
async def upcoming_runs(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
    days: int = Query(default=7, ge=1, le=14),
) -> list[NextRunResponse]:
    """All upcoming runs of the next ``days`` days, sorted by fire time.

    Merges one-off plans and recurring cron schedules (user-skipped occurrences
    excluded) — the data behind the planner's calendar week view.
    """
    until = datetime.now(UTC) + timedelta(days=days)
    return [run for _when, run in upcoming_run_candidates(session, config, scheduler, until)]


def _to_response(plan: Plan, config: AppConfig) -> PlanResponse:
    if plan.zone_id is not None:
        zone = config.zones.get(plan.zone_id)
        zone_label = zone.label if zone else plan.zone_id
        estimated: float | None = None
        if plan.duration_min is not None and zone is not None:
            estimated = round(plan.duration_min / 60.0 * zone.flow_lph, 1)
        return PlanResponse(
            id=plan.id,
            target_type="zone",
            sequence_id=None,
            sequence_label=None,
            zone_id=plan.zone_id,
            zone_label=zone_label,
            label=zone_label,
            scheduled_at=plan.scheduled_at,
            duration_min=plan.duration_min,
            estimated_liters=estimated,
            created_at=plan.created_at,
        )

    seq = config.sequences.get(plan.sequence_id)
    seq_label = seq.label if seq else plan.sequence_id
    estimated = None
    if plan.duration_min is not None and seq is not None:
        total_liters = sum(
            plan.duration_min / 60.0 * config.zones[z].flow_lph
            for z in seq.zones
            if z in config.zones
        )
        estimated = round(total_liters, 1)
    return PlanResponse(
        id=plan.id,
        target_type="sequence",
        sequence_id=plan.sequence_id,
        sequence_label=seq_label,
        zone_id=None,
        zone_label=None,
        label=seq_label,
        scheduled_at=plan.scheduled_at,
        duration_min=plan.duration_min,
        estimated_liters=estimated,
        created_at=plan.created_at,
    )


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> list[PlanResponse]:
    plans = session.exec(
        select(Plan).where(Plan.scheduled_at >= datetime.now(UTC)).order_by(col(Plan.scheduled_at))
    ).all()
    return [_to_response(p, config) for p in plans]


@router.post("", response_model=PlanResponse, status_code=201)
async def create_plan(
    body: CreatePlanRequest,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> PlanResponse:
    # Exactly one target: a sequence plan or a single-zone plan.
    if (body.sequence_id is None) == (body.zone_id is None):
        raise HTTPException(422, "Provide exactly one of sequence_id or zone_id")

    if body.zone_id is not None:
        if body.zone_id not in config.zones:
            raise HTTPException(422, f"Zone '{body.zone_id}' not found")
        if body.duration_min is None:
            raise HTTPException(422, "duration_min is required for a zone plan")
    elif body.sequence_id not in config.sequences:
        raise HTTPException(422, f"Sequence '{body.sequence_id}' not found")

    if body.mode == "in_hours":
        try:
            hours = float(body.value)
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "value must be a number for mode=in_hours") from e
        scheduled_at = datetime.now(UTC) + timedelta(hours=hours)
    elif body.mode == "at_datetime":
        try:
            scheduled_at = datetime.fromisoformat(str(body.value))
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "value must be an ISO 8601 datetime string") from e
        # A naive wall-clock time is meant in the app timezone, not UTC; an aware
        # value is converted from its own offset. Both are stored as naive UTC.
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=ZoneInfo(config.timezone))
    else:
        raise HTTPException(422, f"Unknown mode: {body.mode!r}")

    if scheduled_at <= datetime.now(UTC):
        raise HTTPException(422, "scheduled_at must be in the future")

    plan = Plan(
        id=str(uuid.uuid4()),
        sequence_id=body.sequence_id or "",
        zone_id=body.zone_id,
        scheduled_at=to_naive_utc(scheduled_at, config.timezone),
        duration_min=body.duration_min,
        created_at=datetime.now(UTC),
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return _to_response(plan, config)


@router.delete("/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: str,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> None:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(404, "Plan not found")
    session.delete(plan)
    session.commit()
