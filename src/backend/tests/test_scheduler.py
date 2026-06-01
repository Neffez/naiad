import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.domain.models import Plan, SkippedRun, UserPreference
from naiad.domain.sequences import SequenceRunner, zone_run_id
from naiad.scheduler import (
    _consume_skip,
    _on_rain,
    _plan_tick,
    _run_sequence_job,
    push_notification,
)
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

    def __init__(
        self, season: str = "on", *, prec_prob_today: str = "0", prec_today: str = "0"
    ) -> None:
        self._states = {
            "binary_sensor.jahreszeit": season,
            "binary_sensor.windalarm": "off",
            "binary_sensor.regen": "off",
            "sensor.temperature": "20.0",
            "sensor.prec_prob_today": prec_prob_today,
            "sensor.prec_prob_tomorrow": "0",
            "sensor.prec_today": prec_today,
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
    await runner.stop("seq_1")


async def test_run_sequence_job_skips_when_master_off(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    with Session(engine) as s:
        s.add(UserPreference(key="master_on", value="0"))
        s.commit()
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    assert await _run_sequence_job("seq_1", runner, FakeHA(), fast_config, sf) == "skipped"


async def test_run_sequence_job_skips_when_factor_zero(fast_config: AppConfig, engine) -> None:
    """Heavy forecast rain drives the factor to 0 % → the run is skipped, not
    floored to the range minimum."""
    sf = lambda: Session(engine)  # noqa: E731
    driver = FakeDriver()
    runner = SequenceRunner(fast_config, driver, sf)
    # prob >= threshold_prob (70) and mm >= zero_above_mm (20) → rain factor 0.
    ha = FakeHA(prec_prob_today="100", prec_today="50")
    result = await _run_sequence_job("seq_1", runner, ha, fast_config, sf, triggered_by="cron")
    assert result == "skipped"
    assert driver.on_calls == []  # no valve was opened
    assert not runner.any_running()


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
    await runner.stop("seq_1")
    await _plan_tick(runner, ha, fast_config, sf)
    with Session(engine) as s:
        assert list(s.exec(select(Plan)).all()) == []  # plan consumed
    await runner.stop("seq_1")


async def test_zone_plan_runs_only_that_zone(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    ha = FakeHA()
    driver = FakeDriver()
    runner = SequenceRunner(fast_config, driver, sf)

    with Session(engine) as s:
        s.add(
            Plan(
                id=str(uuid.uuid4()),
                zone_id="zone_b",
                duration_min=1,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        s.commit()

    await _plan_tick(runner, ha, fast_config, sf)
    await asyncio.sleep(0)  # let the run open its zone
    assert "switch.zone_b" in driver.on_calls
    assert "switch.zone_a" not in driver.on_calls
    with Session(engine) as s:
        assert list(s.exec(select(Plan)).all()) == []  # plan consumed
    await runner.stop(zone_run_id("zone_b"))


async def test_zone_plan_skipped_when_master_off(fast_config: AppConfig, engine) -> None:
    sf = lambda: Session(engine)  # noqa: E731
    with Session(engine) as s:
        s.add(UserPreference(key="master_on", value="0"))
        s.add(
            Plan(
                id=str(uuid.uuid4()),
                zone_id="zone_b",
                duration_min=1,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        s.commit()
    driver = FakeDriver()
    runner = SequenceRunner(fast_config, driver, sf)

    await _plan_tick(runner, FakeHA(), fast_config, sf)
    assert driver.on_calls == []  # master off → nothing opened
    with Session(engine) as s:
        assert list(s.exec(select(Plan)).all()) == []  # plan consumed (deterministic skip)


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
    await runner.stop("seq_1")


async def test_rain_discards_paused_run(fast_config: AppConfig, engine) -> None:
    """Rain while a run is paused drops the resume snapshot so it can't resume."""
    from naiad.domain.resume import load_snapshot, save_pause_snapshot

    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    with Session(engine) as s:
        save_pause_snapshot(s, "seq_1", "zone_a", 0, 5.0)

    await _on_rain("binary_sensor.regen", {"state": "on"}, runner, fast_config, FakeHA())

    with Session(engine) as s:
        assert load_snapshot(s, "seq_1") is None


async def test_rain_aborts_all_live_runs(minimal_config: AppConfig, engine) -> None:
    """Rain aborts every live run, not just one."""
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 5.0
        seq["range"] = [0.0, 10.0]
        seq["watchdog_min"] = 60
    config = AppConfig.model_validate(data)
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(config, FakeDriver(), sf)

    await runner.start("seq_1")
    await runner.start("seq_wind")
    await asyncio.sleep(0)
    assert len(runner.running_run_ids()) == 2

    await _on_rain("binary_sensor.regen", {"state": "on"}, runner, config, FakeHA())
    assert not runner.any_running()


async def test_rain_noop_when_nothing_running_or_paused(fast_config: AppConfig, engine) -> None:
    """Rain with no live or paused run is a harmless no-op."""
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(fast_config, FakeDriver(), sf)
    # Must not raise even though there is no run and no snapshot.
    await _on_rain("binary_sensor.regen", {"state": "on"}, runner, fast_config, FakeHA())


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
