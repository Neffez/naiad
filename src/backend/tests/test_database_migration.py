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
