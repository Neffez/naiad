import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

_DATA_DIR = Path(os.environ.get("NAIAD_DATA_DIR", "/data"))
_engine = None


def get_engine():  # type: ignore[return]
    global _engine
    if _engine is None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = _DATA_DIR / "naiad.db"
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _engine


def create_tables() -> None:
    from naiad.domain import models  # noqa: F401 — registers SQLModel metadata
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session
