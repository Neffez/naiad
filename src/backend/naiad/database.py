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
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


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
        "factor_overrides": {"manual_mode": "BOOLEAN", "manual_pct": "INTEGER"},
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
