from datetime import UTC, datetime

from sqlmodel import Session, SQLModel, create_engine

from naiad.api.system import _week_series
from naiad.domain.models import RunHistory


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


def test_week_series_buckets_runs_by_local_weekday() -> None:
    eng = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(eng) as s:
        s.add(
            RunHistory(
                zone_id="z", sequence_id="seq", started_at=now, triggered_by="cron", liters=12.0
            )
        )
        s.commit()

    with Session(eng) as s:
        series = _week_series(s, "UTC")

    assert len(series) == 7
    today_idx = now.weekday()  # 0=Mon..6=Sun
    assert series[today_idx] == 12.0
    assert sum(series) == 12.0


def test_week_series_empty() -> None:
    with Session(_engine()) as s:
        assert _week_series(s, "Europe/Berlin") == [0.0] * 7
