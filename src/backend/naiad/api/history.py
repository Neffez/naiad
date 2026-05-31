from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, delete, func, select

from naiad.api.schemas import (
    DeleteHistoryResponse,
    HistoryEntryResponse,
    PaginatedHistoryResponse,
)
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import RunHistory
from naiad.domain.sequences import zone_id_of_run
from naiad.timeutil import local_date_to_utc, now_utc_naive

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
    # from/to are local calendar dates; convert to naive-UTC bounds (half-open)
    # to match how started_at is stored, so filtering aligns with local days.
    if from_date is not None:
        from_dt = local_date_to_utc(config.timezone, from_date)
        query = query.where(RunHistory.started_at >= from_dt)
    if to_date is not None:
        to_dt = local_date_to_utc(config.timezone, to_date, end_exclusive=True)
        query = query.where(RunHistory.started_at < to_dt)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()

    items = session.exec(
        query.order_by(col(RunHistory.started_at).desc())
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


@router.delete("/history", response_model=DeleteHistoryResponse)
async def delete_history(
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
    older_than_days: int | None = Query(default=None, ge=1),
) -> DeleteHistoryResponse:
    """Delete run history.

    Only ``RunHistory`` rows are removed — settings, plans, schedules and
    sequence overrides are never touched. When ``older_than_days`` is given,
    only entries whose ``started_at`` is older than that many days (relative to
    now, UTC) are deleted; otherwise the entire history is cleared.
    """
    statement = delete(RunHistory)
    if older_than_days is not None:
        cutoff = now_utc_naive() - timedelta(days=older_than_days)
        statement = statement.where(col(RunHistory.started_at) < cutoff)

    result = session.exec(statement)
    session.commit()
    return DeleteHistoryResponse(deleted=result.rowcount)


def _seq_label(sequence_id: str, config: AppConfig) -> str:
    # A standalone single-zone run has no sequence — show nothing for it (the zone
    # label carries the meaning); the synthetic id is internal.
    if zone_id_of_run(sequence_id) is not None:
        return ""
    seq = config.sequences.get(sequence_id)
    return seq.label if seq else sequence_id


def _zone_label(zone_id: str, config: AppConfig) -> str:
    zone = config.zones.get(zone_id)
    return zone.label if zone else zone_id
