"""Frost lockout and cistern guard: optional gates in the shared automatic
start path (run_sequence_job). Both skip deterministically (with a decision-log
row) when their sensor is below the threshold and never block watering when the
sensor is missing or unreadable."""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig, CisternConfig, FrostConfig
from naiad.domain.models import DecisionLog
from naiad.domain.sequences import SequenceRunner
from naiad.scheduler import run_sequence_job
from tests.test_scheduler import FakeDriver, FakeHA

FROST_SENSOR = "sensor.forecast_temp_min"
LEVEL_SENSOR = "sensor.cistern_level"


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def gate_config(minimal_config: AppConfig) -> AppConfig:
    data = minimal_config.model_dump()
    for seq in data["sequences"].values():
        seq["basis_min_per_zone"] = 0.001
        seq["range"] = [0.0, 0.01]
    data["frost"] = {"enabled": True, "temperature_min": FROST_SENSOR, "threshold_c": 3.0}
    data["cistern"] = {"enabled": True, "level_entity": LEVEL_SENSOR, "min_level": 20.0}
    return AppConfig.model_validate(data)


def _ha(frost: str | None, level: str | None) -> FakeHA:
    ha = FakeHA()
    if frost is not None:
        ha._states[FROST_SENSOR] = frost
    if level is not None:
        ha._states[LEVEL_SENSOR] = level
    return ha


def _single_decision(engine) -> DecisionLog:
    with Session(engine) as session:
        rows = list(session.exec(select(DecisionLog)).all())
    assert len(rows) == 1
    return rows[0]


async def test_frost_below_threshold_skips_with_decision(gate_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost="1.5", level="80")

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "skipped"

    row = _single_decision(engine)
    assert row.decision == "skipped"
    assert row.reason == "frost"
    assert row.factor_pct is not None  # logged with the inputs it would have used


async def test_frost_at_threshold_runs(gate_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost="3.0", level="80")

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "started"
    await runner.stop("seq_1")


async def test_unreadable_frost_sensor_never_blocks(gate_config: AppConfig) -> None:
    """A broken/missing sensor must not stop watering — the gate is skipped."""
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost=None, level="80")  # entity unknown to HA

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "started"
    await runner.stop("seq_1")


async def test_frost_disabled_ignores_sensor(gate_config: AppConfig) -> None:
    data = gate_config.model_dump()
    data["frost"]["enabled"] = False
    config = AppConfig.model_validate(data)
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(config, FakeDriver(), sf)
    ha = _ha(frost="-5.0", level="80")

    assert await run_sequence_job("seq_1", runner, ha, config, sf) == "started"
    await runner.stop("seq_1")


async def test_cistern_below_minimum_skips_with_decision(gate_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost="10", level="12.5")

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "skipped"

    row = _single_decision(engine)
    assert row.decision == "skipped"
    assert row.reason == "cistern_low"


async def test_cistern_at_minimum_runs(gate_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost="10", level="20.0")

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "started"
    await runner.stop("seq_1")


async def test_unreadable_cistern_sensor_never_blocks(gate_config: AppConfig) -> None:
    engine = _engine()
    sf = lambda: Session(engine)  # noqa: E731
    runner = SequenceRunner(gate_config, FakeDriver(), sf)
    ha = _ha(frost="10", level="unavailable")

    assert await run_sequence_job("seq_1", runner, ha, gate_config, sf) == "started"
    await runner.stop("seq_1")


def test_frost_enabled_requires_sensor() -> None:
    with pytest.raises(ValueError, match="temperature_min"):
        FrostConfig(enabled=True, temperature_min="")


def test_cistern_enabled_requires_sensor() -> None:
    with pytest.raises(ValueError, match="level_entity"):
        CisternConfig(enabled=True, level_entity="")
