import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from naiad.api.schemas import CreatePlanRequest, PlanResponse
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import Plan

router = APIRouter(prefix="/plans", tags=["plans"])


def _to_response(plan: Plan, config: AppConfig) -> PlanResponse:
    seq = config.sequences.get(plan.sequence_id)
    seq_label = seq.label if seq else plan.sequence_id
    estimated: float | None = None
    if plan.duration_min is not None and seq is not None:
        total_liters = sum(
            plan.duration_min / 60.0 * config.zones[z].flow_lph
            for z in seq.zones
            if z in config.zones
        )
        estimated = round(total_liters, 1)
    return PlanResponse(
        id=plan.id,
        sequence_id=plan.sequence_id,
        sequence_label=seq_label,
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
    if body.sequence_id not in config.sequences:
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
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "value must be an ISO 8601 datetime string") from e
    else:
        raise HTTPException(422, f"Unknown mode: {body.mode!r}")

    if scheduled_at <= datetime.now(UTC):
        raise HTTPException(422, "scheduled_at must be in the future")

    plan = Plan(
        id=str(uuid.uuid4()),
        sequence_id=body.sequence_id,
        scheduled_at=scheduled_at,
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
