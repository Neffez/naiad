import pytest
from sqlmodel import Session, SQLModel, create_engine

from naiad.domain.resume import (
    clear_all_snapshots,
    clear_snapshot,
    load_snapshot,
    save_pause_snapshot,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_save_and_load_snapshot(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 12.5)
    snap = load_snapshot(session, "seq_1")
    assert snap is not None
    assert snap.zone_id == "zone_a"
    assert snap.zone_index == 0
    assert snap.remaining_min == pytest.approx(12.5)


def test_load_wrong_sequence_returns_none(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 5.0)
    assert load_snapshot(session, "seq_2") is None


def test_load_nonexistent_returns_none(session: Session) -> None:
    assert load_snapshot(session, "seq_1") is None


def test_clear_snapshot(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 5.0)
    clear_snapshot(session, "seq_1")
    assert load_snapshot(session, "seq_1") is None


def test_clear_wrong_sequence_does_nothing(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 5.0)
    clear_snapshot(session, "seq_other")
    assert load_snapshot(session, "seq_1") is not None


def test_multiple_snapshots_coexist(session: Session) -> None:
    """Each paused sequence keeps its own snapshot — starting/pausing another
    sequence no longer abandons the first."""
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 5.0)
    save_pause_snapshot(session, "seq_2", "zone_b", 1, 3.0)
    assert load_snapshot(session, "seq_1") is not None
    assert load_snapshot(session, "seq_2") is not None


def test_clear_all_snapshots_returns_ids_and_drops_all(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 5.0)
    save_pause_snapshot(session, "seq_2", "zone_b", 1, 3.0)
    cleared = clear_all_snapshots(session)
    assert set(cleared) == {"seq_1", "seq_2"}
    assert load_snapshot(session, "seq_1") is None
    assert load_snapshot(session, "seq_2") is None


def test_clear_all_snapshots_empty(session: Session) -> None:
    assert clear_all_snapshots(session) == []


def test_save_overwrites_existing(session: Session) -> None:
    save_pause_snapshot(session, "seq_1", "zone_a", 0, 10.0)
    save_pause_snapshot(session, "seq_1", "zone_b", 1, 7.0)
    snap = load_snapshot(session, "seq_1")
    assert snap is not None
    assert snap.zone_id == "zone_b"
    assert snap.zone_index == 1
    assert snap.remaining_min == pytest.approx(7.0)
