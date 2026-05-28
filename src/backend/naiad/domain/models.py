from datetime import datetime

from sqlmodel import Field, SQLModel


class RunHistory(SQLModel, table=True):
    __tablename__ = "run_history"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    zone_id: str
    sequence_id: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_min: float | None = None
    liters: float | None = None
    triggered_by: str  # cron | manual | plan | resume
    aborted: bool = False
    abort_reason: str | None = None  # rain | watchdog | manual_stop | ha_disconnect


class Plan(SQLModel, table=True):
    __tablename__ = "plans"  # type: ignore[assignment]

    id: str = Field(primary_key=True)  # UUID
    sequence_id: str
    scheduled_at: datetime
    duration_min: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuthToken(SQLModel, table=True):
    __tablename__ = "auth_tokens"  # type: ignore[assignment]

    token: str = Field(primary_key=True)
    device_label: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: datetime | None = None
    expires_at: datetime


class UserPreference(SQLModel, table=True):
    __tablename__ = "user_preferences"  # type: ignore[assignment]

    key: str = Field(primary_key=True)
    value: str


class ResumeSnapshot(SQLModel, table=True):
    """Manual-pause state only. Rain abort writes no snapshot."""

    __tablename__ = "resume_snapshot"  # type: ignore[assignment]

    id: int = Field(default=1, primary_key=True)
    sequence_id: str
    zone_id: str
    zone_index: int
    remaining_min: float
    paused_at: datetime


class SequenceOverride(SQLModel, table=True):
    """Per-sequence user overrides. NULL = use YAML default."""

    __tablename__ = "sequence_overrides"  # type: ignore[assignment]

    sequence_id: str = Field(primary_key=True)
    basis_min_per_zone: int | None = None
    watchdog_min: int | None = None
    paused: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FactorOverride(SQLModel, table=True):
    """Factor parameter overrides — singleton (id always = 1). NULL = use YAML default."""

    __tablename__ = "factor_overrides"  # type: ignore[assignment]

    id: int = Field(default=1, primary_key=True)
    temp_basis_c: float | None = None
    temp_pct_per_c: float | None = None
    temp_min_pct: int | None = None
    temp_max_pct: int | None = None
    rain_forecast_days: int | None = None
    rain_threshold_prob: int | None = None
    rain_reduce_above_mm: float | None = None
    rain_zero_above_mm: float | None = None
    rain_forecast_decay: float | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
