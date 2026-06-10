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


async def test_history_summary_aggregates_window(minimal_config) -> None:
    """The summary aggregates liters/runs/avg duration over the local calendar
    window — and ignores rows outside it as well as unfinished durations."""
    from naiad.api.history import get_history_summary

    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(eng) as s:
        s.add(
            RunHistory(
                zone_id="z",
                sequence_id="seq",
                started_at=now,
                triggered_by="cron",
                liters=10.0,
                duration_min=20.0,
            )
        )
        s.add(
            RunHistory(
                zone_id="z",
                sequence_id="seq",
                started_at=now - timedelta(days=2),
                triggered_by="cron",
                liters=5.0,
                duration_min=10.0,
            )
        )
        # In-flight run: liters/duration still NULL — counted as a run, ignored in avg.
        s.add(RunHistory(zone_id="z", sequence_id="seq", started_at=now, triggered_by="cron"))
        # Outside the 7-day window.
        s.add(
            RunHistory(
                zone_id="z",
                sequence_id="seq",
                started_at=now - timedelta(days=30),
                triggered_by="cron",
                liters=99.0,
                duration_min=99.0,
            )
        )
        s.commit()

    with Session(eng) as s:
        result = await get_history_summary(_=None, config=minimal_config, session=s, days=7)

    assert result.days == 7
    assert result.liters == 15.0
    assert result.runs == 3
    assert result.avg_duration_min == 15.0


async def test_history_summary_empty_window(minimal_config) -> None:
    from naiad.api.history import get_history_summary

    eng = _engine()
    with Session(eng) as s:
        result = await get_history_summary(_=None, config=minimal_config, session=s, days=7)

    assert result.liters == 0.0
    assert result.runs == 0
    assert result.avg_duration_min is None
