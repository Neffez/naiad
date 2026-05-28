from datetime import UTC, datetime

from sqlmodel import Session

from naiad.domain.models import ResumeSnapshot


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
        session.add(ResumeSnapshot(
            id=1,
            sequence_id=sequence_id,
            zone_id=zone_id,
            zone_index=zone_index,
            remaining_min=remaining_min,
            paused_at=datetime.now(UTC),
        ))
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
