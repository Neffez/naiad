import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

_DATA_DIR = Path(os.environ.get("NAIAD_DATA_DIR", "/data"))
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = _DATA_DIR / "naiad.db"
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _engine


def create_tables() -> None:
    from naiad.domain import models  # noqa: F401 — registers SQLModel metadata

    engine = get_engine()
    _drop_legacy_singleton_tables(engine)
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _drop_legacy_singleton_tables(engine: Engine) -> None:
    """Drop the old single-row (id=1 PK) recovery tables so they are recreated
    with the new ``sequence_id`` primary key.

    ``resume_snapshot`` and ``active_run`` switched from a singleton ``id`` PK to
    one row per sequence (parallel runs). ``create_all`` never alters an existing
    table's primary key, so a table left over from an older version must be
    dropped. These hold only ephemeral pause/crash-recovery state, so dropping
    them is safe — at worst a run interrupted exactly across the upgrade is not
    recovered.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    for table in ("resume_snapshot", "active_run"):
        if not inspector.has_table(table):
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if "id" in columns:  # legacy singleton schema
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE {table}"))


def _add_missing_columns(engine: Engine) -> None:
    """Add nullable columns introduced after a table was first created.

    ``SQLModel.metadata.create_all`` only creates whole tables — it never ALTERs
    an existing one. New optional columns must therefore be added explicitly so a
    database created by an older version keeps working without a data migration.
    """
    from sqlalchemy import inspect, text

    additions: dict[str, dict[str, str]] = {
        # table: {column: SQL type}
        "plans": {"zone_id": "VARCHAR"},
        "active_run": {"switch": "VARCHAR"},
        "factor_overrides": {
            "manual_mode": "BOOLEAN",
            "manual_pct": "INTEGER",
            "rain_peak_tomorrow": "BOOLEAN",
        },
    }
    inspector = inspect(engine)
    for table, columns in additions.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column not in existing:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
