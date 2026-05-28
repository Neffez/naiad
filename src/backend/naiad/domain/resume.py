from datetime import UTC, datetime

from sqlmodel import Session

from naiad.domain.models import ActiveRun, ResumeSnapshot


def save_pause_snapshot(
    session: Session,
    sequence_id: str,
    zone_id: str,
    zone_index: int,
    remaining_min: float,
) -> None:
    existing = session.get(ResumeSnapshot, 1)
    if existing:
        existing.sequence_id = sequence_id
        existing.zone_id = zone_id
        existing.zone_index = zone_index
        existing.remaining_min = remaining_min
        existing.paused_at = datetime.now(UTC)
        session.add(existing)
    else:
        session.add(
            ResumeSnapshot(
                id=1,
                sequence_id=sequence_id,
                zone_id=zone_id,
                zone_index=zone_index,
                remaining_min=remaining_min,
                paused_at=datetime.now(UTC),
            )
        )
    session.commit()


def load_snapshot(session: Session, sequence_id: str) -> ResumeSnapshot | None:
    snap = session.get(ResumeSnapshot, 1)
    if snap is None or snap.sequence_id != sequence_id:
        return None
    return snap


def clear_snapshot(session: Session, sequence_id: str) -> None:
    snap = session.get(ResumeSnapshot, 1)
    if snap and snap.sequence_id == sequence_id:
        session.delete(snap)
        session.commit()


def clear_orphan_snapshot(session: Session, current_sequence_id: str) -> None:
    """Drop a pause snapshot left by a *different* sequence.

    Starting sequence B abandons a paused sequence A — otherwise A's snapshot
    lingers and the API keeps reporting A as 'paused' forever.
    """
    snap = session.get(ResumeSnapshot, 1)
    if snap and snap.sequence_id != current_sequence_id:
        session.delete(snap)
        session.commit()


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
    existing = session.get(ActiveRun, 1)
    if existing:
        existing.sequence_id = sequence_id
        existing.zone_index = zone_index
        existing.zone_started_at = zone_started_at
        existing.zone_planned_min = zone_planned_min
        existing.run_duration_min = run_duration_min
        existing.triggered_by = triggered_by
        session.add(existing)
    else:
        session.add(
            ActiveRun(
                id=1,
                sequence_id=sequence_id,
                zone_index=zone_index,
                zone_started_at=zone_started_at,
                zone_planned_min=zone_planned_min,
                run_duration_min=run_duration_min,
                triggered_by=triggered_by,
            )
        )
    session.commit()


def load_active_run(session: Session) -> ActiveRun | None:
    return session.get(ActiveRun, 1)


def clear_active_run(session: Session) -> None:
    rec = session.get(ActiveRun, 1)
    if rec:
        session.delete(rec)
        session.commit()
