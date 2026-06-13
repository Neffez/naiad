from sqlalchemy import inspect, text
from sqlmodel import create_engine

from naiad.database import _add_missing_columns


def _columns(engine, table: str) -> set[str]:
    return {col["name"] for col in inspect(engine).get_columns(table)}


def test_adds_zone_id_to_legacy_plans_table() -> None:
    """A plans table created before zone_id existed gains the column in place."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        # Legacy schema: no zone_id column.
        conn.execute(
            text(
                "CREATE TABLE plans ("
                "id VARCHAR PRIMARY KEY, sequence_id VARCHAR NOT NULL, "
                "scheduled_at DATETIME, duration_min INTEGER, created_at DATETIME)"
            )
        )

    assert "zone_id" not in _columns(engine, "plans")
    _add_missing_columns(engine)
    assert "zone_id" in _columns(engine, "plans")


def test_adds_switch_to_legacy_active_run_table() -> None:
    """A crash-recovery table created before switch tracking gains the column."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE active_run ("
                "sequence_id VARCHAR PRIMARY KEY, zone_index INTEGER NOT NULL, "
                "zone_started_at DATETIME NOT NULL, zone_planned_min FLOAT NOT NULL, "
                "run_duration_min FLOAT NOT NULL, triggered_by VARCHAR NOT NULL)"
            )
        )

    assert "switch" not in _columns(engine, "active_run")
    _add_missing_columns(engine)
    assert "switch" in _columns(engine, "active_run")


def test_add_missing_columns_is_idempotent() -> None:
    """Running the migration twice (column already present) is a no-op, not an error."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE plans ("
                "id VARCHAR PRIMARY KEY, sequence_id VARCHAR NOT NULL, zone_id VARCHAR, "
                "scheduled_at DATETIME, duration_min INTEGER, created_at DATETIME)"
            )
        )

    _add_missing_columns(engine)
    _add_missing_columns(engine)  # must not raise
    assert "zone_id" in _columns(engine, "plans")


def test_no_plans_table_is_skipped() -> None:
    """The migration tolerates a database where the table does not yet exist."""
    engine = create_engine("sqlite:///:memory:")
    _add_missing_columns(engine)  # must not raise
    assert not inspect(engine).has_table("plans")


def test_adds_rain_peak_tomorrow_to_legacy_factor_overrides() -> None:
    """A factor_overrides table created before peak_tomorrow existed gains the column."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        # Legacy schema: rain factor columns but no rain_peak_tomorrow.
        conn.execute(
            text(
                "CREATE TABLE factor_overrides ("
                "id INTEGER PRIMARY KEY, rain_forecast_decay FLOAT, updated_at DATETIME)"
            )
        )

    assert "rain_peak_tomorrow" not in _columns(engine, "factor_overrides")
    _add_missing_columns(engine)
    assert "rain_peak_tomorrow" in _columns(engine, "factor_overrides")


def test_adds_et0_reservoir_to_legacy_factor_overrides() -> None:
    """A factor_overrides table created before the et0 rain mode gains the column."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE factor_overrides ("
                "id INTEGER PRIMARY KEY, rain_forecast_decay FLOAT, updated_at DATETIME)"
            )
        )

    assert "rain_et0_reservoir_mm" not in _columns(engine, "factor_overrides")
    _add_missing_columns(engine)
    assert "rain_et0_reservoir_mm" in _columns(engine, "factor_overrides")
