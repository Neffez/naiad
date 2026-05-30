import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import Plan, SkippedRun, UserPreference
from naiad.domain.sequences import SequenceRunner
from naiad.scheduler import _consume_skip, _plan_tick, _run_sequence_job, push_notification
from tests.conftest import MINIMAL_CONFIG_DATA


class FakeDriver:
    def __init__(self) -> None:
        self.on_calls: list[str] = []
        self.off_calls: list[str] = []

    async def turn_on(self, zone: Any) -> None:
        self.on_calls.append(zone.switch)

    async def turn_off(self, zone: Any) -> None:
        self.off_calls.append(zone.switch)

    def subscribe_state(self, zone: Any, cb: Any) -> None:
        pass


class FakeHA:
    """Sensor cache that keeps the season on and the weather neutral."""

    def __init__(self, season: str = "on") -> None:
        self._states = {
            "binary_sensor.jahreszeit": season,
            "binary_sensor.windalarm": "off",
            "binary_sensor.regen": "off",
            "sensor.temperature": "20.0",
            "sensor.prec_prob_today": "0",
            "sensor.prec_prob_tomorrow": "0",
            "sensor.prec_today": "0",
            "sensor.prec_tomorrow": "0",
        }

    def get_state_value(self, entity_id: str) -> str | None:
        return self._states.get(entity_id)

    def get_cached_daily_max(self, entity_id: str) -> float | None:
        return None

    @property
    def is_connected(self) -> bool:
        return True


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def fast_config(minimal_config: AppConfig) -> AppConfig:
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 0.001
        seq["range"] = [0.0, 0.01]
    return AppConfig.model_validate(data)


async def test_run_sequence_job_status_transitions(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    ha = FakeHA()

    assert await _run_sequence_job("seq_1", runner, ha, fast_config, sf) == "started"
    # Second start while running → transient conflict.
    assert await _run_sequence_job("seq_1", runner, ha, fast_config, sf) == "conflict"
    await runner.stop()


async def test_run_sequence_job_skips_when_master_off(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    with Session(engine) as s:
        s.add(UserPreference(key="master_on", value="0"))
        s.commit()
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    assert await _run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "skipped"


async def test_run_sequence_job_skips_when_season_off(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    result = await _run_sequence_job("seq_1", runner, FakeHA(season="off"), fast_config, sf)
    assert result == "skipped"


async def test_plan_kept_on_conflict_then_consumed(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    ha = FakeHA()
    runner = SequenceRunner(fast_config, FakeDriver(), sf)

    # A plan for seq_1 is due now.
    with Session(engine) as s:
        s.add(
            Plan(
                id=str(uuid.uuid4()),
                sequence_id="seq_1",
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        s.commit()

    # Block with a running seq_1 so the plan tick hits a conflict.
    await runner.start("seq_1")
    await _plan_tick(runner, ha, fast_config, sf)
    with Session(engine) as s:
        assert len(list(s.exec(select(Plan)).all())) == 1  # plan retained on conflict

    # Free the runner; the next tick consumes the plan.
    await runner.stop()
    await _plan_tick(runner, ha, fast_config, sf)
    with Session(engine) as s:
        assert list(s.exec(select(Plan)).all()) == []  # plan consumed
    await runner.stop()


async def test_cron_run_skipped_when_occurrence_marked(fast_config: AppConfig, engine) -> None:
    """A user-skipped scheduled occurrence is consumed and suppresses that run."""
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    ha = FakeHA()

    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    with Session(engine) as s:
        s.add(SkippedRun(sequence_id="seq_1", scheduled_at=now))
        s.commit()

    result = await _run_sequence_job("seq_1", runner, ha, fast_config, sf, triggered_by="cron")
    assert result == "skipped"
    # The skip record is consumed (one-off), so the next run is unaffected.
    with Session(engine) as s:
        assert list(s.exec(select(SkippedRun)).all()) == []


async def test_manual_trigger_ignores_skip(fast_config: AppConfig, engine) -> None:
    """A skip only suppresses the matching cron fire, not a manual/plan start."""
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    ha = FakeHA()

    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    with Session(engine) as s:
        s.add(SkippedRun(sequence_id="seq_1", scheduled_at=now))
        s.commit()

    result = await _run_sequence_job("seq_1", runner, ha, fast_config, sf, triggered_by="plan")
    assert result == "started"
    await runner.stop()


def test_consume_skip_prunes_stale(engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    now = datetime.now(UTC)
    stale = now.replace(tzinfo=None) - timedelta(days=2)
    with Session(engine) as s:
        s.add(SkippedRun(sequence_id="seq_1", scheduled_at=stale))
        s.commit()

    # No match for "now", but the stale record is pruned.
    assert _consume_skip(sf, "seq_1", now) is False
    with Session(engine) as s:
        assert list(s.exec(select(SkippedRun)).all()) == []


# ── Notifications: gating + quiet (push_notification) ──────────────────────────


class _RecordingHA:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_service(self, domain: str, service: str, **data: Any) -> None:
        self.calls.append((domain, service, data))


def _cfg_targets(targets: list[Any]) -> AppConfig:
    import copy

    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["ha"]["notify_targets"] = targets
    return AppConfig.model_validate(data)


async def test_push_sends_to_subscribed_target() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets([{"service": "notify.a", "categories": ["start"]}])
    await push_notification(ha, cfg, "hi", category="start")
    assert ha.calls == [("notify", "a", {"message": "hi"})]


async def test_push_skips_unsubscribed_target() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets([{"service": "notify.a", "categories": ["reminder"]}])
    await push_notification(ha, cfg, "hi", category="start")
    assert ha.calls == []


async def test_push_quiet_android_sets_importance() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets(
        [{"service": "notify.a", "categories": ["abort"], "quiet": True, "platform": "android"}]
    )
    await push_notification(ha, cfg, "hi", category="abort")
    assert ha.calls[0][2]["data"] == {"importance": "low"}


async def test_push_quiet_ios_sets_passive() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets(
        [{"service": "notify.a", "categories": ["abort"], "quiet": True, "platform": "ios"}]
    )
    await push_notification(ha, cfg, "hi", category="abort")
    assert ha.calls[0][2]["data"]["push"]["interruption-level"] == "passive"


async def test_push_info_category_sends_regardless_of_subscriptions() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets([{"service": "notify.a", "categories": []}])
    await push_notification(ha, cfg, "hi", category="info")
    assert len(ha.calls) == 1


async def test_push_legacy_string_target_gets_all_categories() -> None:
    ha = _RecordingHA()
    cfg = _cfg_targets(["notify.a"])  # back-compat: plain string
    await push_notification(ha, cfg, "hi", category="reminder")
    assert ha.calls == [("notify", "a", {"message": "hi"})]


async def test_push_no_targets_is_noop() -> None:
    ha = _RecordingHA()
    await push_notification(ha, _cfg_targets([]), "hi", category="start")
    assert ha.calls == []
