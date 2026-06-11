from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, delete, func, select

from naiad.api.schemas import (
    DecisionEntryResponse,
    DeleteHistoryResponse,
    HistoryEntryResponse,
    HistorySummaryResponse,
    PaginatedDecisionsResponse,
    PaginatedHistoryResponse,
)
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import DecisionLog, RunHistory
from naiad.domain.sequences import zone_id_of_run
from naiad.timeutil import local_date_to_utc, local_day_start_utc, now_utc_naive

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


@router.get("/history/decisions", response_model=PaginatedDecisionsResponse)
async def get_decisions(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    sequence_id: str | None = Query(default=None),
) -> PaginatedDecisionsResponse:
    """Paginated decision log: why each automatic run started or was skipped."""
    query = select(DecisionLog)
    if sequence_id is not None:
        query = query.where(DecisionLog.sequence_id == sequence_id)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()

    items = session.exec(
        query.order_by(col(DecisionLog.created_at).desc(), col(DecisionLog.id).desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    return PaginatedDecisionsResponse(
        items=[
            DecisionEntryResponse(
                id=row.id or 0,
                created_at=row.created_at,
                sequence_id=row.sequence_id,
                sequence_label=_seq_label(row.sequence_id, config),
                triggered_by=row.triggered_by,
                decision=row.decision,
                reason=row.reason,
                factor_pct=row.factor_pct,
                temp_delta_pct=row.temp_delta_pct,
                rain_factor_pct=row.rain_factor_pct,
                temp_c=row.temp_c,
                rain_today_mm=row.rain_today_mm,
                rain_tomorrow_mm=row.rain_tomorrow_mm,
                rain_prob_today_pct=row.rain_prob_today_pct,
                rain_prob_tomorrow_pct=row.rain_prob_tomorrow_pct,
                rain_credit_mm=row.rain_credit_mm,
                rain_mode=row.rain_mode,
                manual_factor=row.manual_factor,
            )
            for row in items
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/history/summary", response_model=HistorySummaryResponse)
async def get_history_summary(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    days: int = Query(default=7, ge=1, le=365),
) -> HistorySummaryResponse:
    """Aggregate over the last ``days`` local calendar days (today included).

    Computed in SQL so it is exact regardless of how many runs the window holds
    — unlike a client summing one page of /history rows.
    """
    # Window start: local midnight of (today - (days - 1)), as naive UTC to
    # match how started_at is stored.
    start = local_day_start_utc(config.timezone) - timedelta(days=days - 1)

    liters, runs, avg_duration = session.exec(
        select(
            func.coalesce(func.sum(RunHistory.liters), 0.0),
            func.count(),
            func.avg(RunHistory.duration_min),  # AVG ignores NULL (in-flight) rows
        ).where(RunHistory.started_at >= start)
    ).one()

    return HistorySummaryResponse(
        days=days,
        liters=round(float(liters or 0.0), 1),
        runs=int(runs),
        avg_duration_min=round(float(avg_duration), 1) if avg_duration is not None else None,
    )


@router.delete("/history", response_model=DeleteHistoryResponse)
async def delete_history(
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
    older_than_days: int | None = Query(default=None, ge=1),
) -> DeleteHistoryResponse:
    """Delete run history (runs and the decision log).

    Only ``RunHistory`` and ``DecisionLog`` rows are removed — settings, plans,
    schedules and sequence overrides are never touched. When ``older_than_days``
    is given, only entries older than that many days (relative to now, UTC) are
    deleted; otherwise the entire history is cleared. ``deleted`` counts the
    removed run rows only.
    """
    statement = delete(RunHistory)
    decisions = delete(DecisionLog)
    if older_than_days is not None:
        cutoff = now_utc_naive() - timedelta(days=older_than_days)
        statement = statement.where(col(RunHistory.started_at) < cutoff)
        decisions = decisions.where(col(DecisionLog.created_at) < cutoff)

    result = session.exec(statement)
    session.exec(decisions)
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
