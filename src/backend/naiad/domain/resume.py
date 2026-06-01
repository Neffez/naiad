from datetime import UTC, datetime

from sqlmodel import Session, select

from naiad.domain.models import ActiveRun, ResumeSnapshot


def save_pause_snapshot(
    session: Session,
    sequence_id: str,
    zone_id: str,
    zone_index: int,
    remaining_min: float,
) -> None:
    existing = session.get(ResumeSnapshot, sequence_id)
    if existing:
        existing.zone_id = zone_id
        existing.zone_index = zone_index
        existing.remaining_min = remaining_min
        existing.paused_at = datetime.now(UTC)
        session.add(existing)
    else:
        session.add(
            ResumeSnapshot(
                sequence_id=sequence_id,
                zone_id=zone_id,
                zone_index=zone_index,
                remaining_min=remaining_min,
                paused_at=datetime.now(UTC),
            )
        )
    session.commit()


def load_snapshot(session: Session, sequence_id: str) -> ResumeSnapshot | None:
    return session.get(ResumeSnapshot, sequence_id)


def clear_snapshot(session: Session, sequence_id: str) -> None:
    snap = session.get(ResumeSnapshot, sequence_id)
    if snap:
        session.delete(snap)
        session.commit()


def clear_all_snapshots(session: Session) -> list[str]:
    """Drop every pause snapshot, returning their sequence ids.

    Used to cancel all paused runs on rain so none can later be resumed.
    """
    snaps = list(session.exec(select(ResumeSnapshot)).all())
    ids = [s.sequence_id for s in snaps]
    for snap in snaps:
        session.delete(snap)
    if snaps:
        session.commit()
    return ids


# ── Active-run record (crash recovery) ────────────────────────────────────────


def save_active_run(
    session: Session,
    sequence_id: str,
    zone_index: int,
    zone_started_at: datetime,
    zone_planned_min: float,
    run_duration_min: float,
    triggered_by: str,
) -> None:
    existing = session.get(ActiveRun, sequence_id)
    if existing:
        existing.zone_index = zone_index
        existing.zone_started_at = zone_started_at
        existing.zone_planned_min = zone_planned_min
        existing.run_duration_min = run_duration_min
        existing.triggered_by = triggered_by
        session.add(existing)
    else:
        session.add(
            ActiveRun(
                sequence_id=sequence_id,
                zone_index=zone_index,
                zone_started_at=zone_started_at,
                zone_planned_min=zone_planned_min,
                run_duration_min=run_duration_min,
                triggered_by=triggered_by,
            )
        )
    session.commit()


def load_active_runs(session: Session) -> list[ActiveRun]:
    return list(session.exec(select(ActiveRun)).all())


def clear_active_run(session: Session, sequence_id: str) -> None:
    rec = session.get(ActiveRun, sequence_id)
    if rec:
        session.delete(rec)
        session.commit()
