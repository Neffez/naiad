from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from naiad.api.history import delete_history
from naiad.domain.models import Plan, RunHistory, SequenceOverride


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def _run(session: Session, started_at: datetime) -> None:
    session.add(
        RunHistory(zone_id="z", sequence_id="seq", started_at=started_at, triggered_by="cron")
    )


async def test_delete_all_history_clears_runs() -> None:
    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(eng) as s:
        _run(s, now)
        _run(s, now - timedelta(days=100))
        s.commit()

    with Session(eng) as s:
        result = await delete_history(_=None, session=s, older_than_days=None)

    assert result.deleted == 2
    with Session(eng) as s:
        assert s.exec(select(RunHistory)).all() == []


async def test_delete_older_than_keeps_recent_runs() -> None:
    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    recent = now - timedelta(days=5)
    old = now - timedelta(days=40)
    with Session(eng) as s:
        _run(s, recent)
        _run(s, old)
        s.commit()

    with Session(eng) as s:
        result = await delete_history(_=None, session=s, older_than_days=30)

    assert result.deleted == 1
    with Session(eng) as s:
        remaining = s.exec(select(RunHistory)).all()
        assert len(remaining) == 1
        assert remaining[0].started_at == recent


async def test_delete_history_leaves_settings_and_plans_untouched() -> None:
    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(eng) as s:
        _run(s, now)
        s.add(Plan(id="p1", sequence_id="seq", scheduled_at=now, duration_min=10))
        s.add(SequenceOverride(sequence_id="seq", basis_min_per_zone=12))
        s.commit()

    with Session(eng) as s:
        await delete_history(_=None, session=s, older_than_days=None)

    with Session(eng) as s:
        assert s.exec(select(RunHistory)).all() == []
        assert len(s.exec(select(Plan)).all()) == 1
        assert len(s.exec(select(SequenceOverride)).all()) == 1
