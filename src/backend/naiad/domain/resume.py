from datetime import UTC, datetime

from sqlmodel import Session, select

from naiad.domain.models import ActiveRun, PendingClose, ResumeSnapshot


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
    switch: str | None = None,
) -> None:
    existing = session.get(ActiveRun, sequence_id)
    if existing:
        existing.zone_index = zone_index
        existing.zone_started_at = zone_started_at
        existing.zone_planned_min = zone_planned_min
        existing.run_duration_min = run_duration_min
        existing.triggered_by = triggered_by
        existing.switch = switch
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
                switch=switch,
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


# ── Pending valve closes (per-switch durable close retry) ─────────────────────


def save_pending_close(session: Session, switch: str, zone_id: str | None = None) -> None:
    """Record that the valve entity ``switch`` may still be open.

    Keyed by ``switch``: a failure for a different switch never overwrites this
    record, and ``created_at`` is preserved across repeated failures for the same
    switch. ``zone_id`` is informational only.
    """
    if session.get(PendingClose, switch) is None:
        session.add(PendingClose(switch=switch, zone_id=zone_id))
        session.commit()


def load_pending_closes(session: Session) -> list[PendingClose]:
    return list(session.exec(select(PendingClose)).all())


def clear_pending_close(session: Session, switch: str) -> None:
    """Clear the pending close for exactly this switch entity (never another)."""
    rec = session.get(PendingClose, switch)
    if rec:
        session.delete(rec)
        session.commit()
