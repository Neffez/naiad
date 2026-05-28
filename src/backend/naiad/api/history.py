from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, func, select

from naiad.api.schemas import HistoryEntryResponse, PaginatedHistoryResponse
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import RunHistory

router = APIRouter(tags=["history"])


@router.get("/history", response_model=PaginatedHistoryResponse)
async def get_history(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    sequence_id: str | None = Query(default=None),
    zone_id: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> PaginatedHistoryResponse:
    query = select(RunHistory)

    if sequence_id is not None:
        query = query.where(RunHistory.sequence_id == sequence_id)
    if zone_id is not None:
        query = query.where(RunHistory.zone_id == zone_id)
    if from_date is not None:
        from_dt = datetime(from_date.year, from_date.month, from_date.day)
        query = query.where(RunHistory.started_at >= from_dt)
    if to_date is not None:
        to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59)
        query = query.where(RunHistory.started_at <= to_dt)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()

    items = session.exec(
        query.order_by(RunHistory.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    return PaginatedHistoryResponse(
        items=[
            HistoryEntryResponse(
                id=row.id or 0,
                zone_id=row.zone_id,
                zone_label=_zone_label(row.zone_id, config),
                sequence_id=row.sequence_id,
                sequence_label=_seq_label(row.sequence_id, config),
                started_at=row.started_at,
                ended_at=row.ended_at,
                duration_min=row.duration_min,
                liters=row.liters,
                triggered_by=row.triggered_by,
                aborted=row.aborted,
                abort_reason=row.abort_reason,
            )
            for row in items
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


def _seq_label(sequence_id: str, config: AppConfig) -> str:
    seq = config.sequences.get(sequence_id)
    return seq.label if seq else sequence_id


def _zone_label(zone_id: str, config: AppConfig) -> str:
    zone = config.zones.get(zone_id)
    return zone.label if zone else zone_id
