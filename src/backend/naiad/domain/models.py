from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class RunHistory(SQLModel, table=True):
    __tablename__ = "run_history"

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
    __tablename__ = "plans"

    id: str = Field(primary_key=True)  # UUID
    sequence_id: str
    scheduled_at: datetime
    duration_min: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SkippedRun(SQLModel, table=True):
    """A single scheduled cron occurrence the user chose to skip.

    Matched by sequence and the occurrence's fire time (naive UTC, minute
    precision). The scheduler consumes a matching record when the cron job fires,
    so only that one run is skipped — the next scheduled run happens as usual.
    """

    __tablename__ = "skipped_runs"

    id: int | None = Field(default=None, primary_key=True)
    sequence_id: str
    scheduled_at: datetime  # naive UTC, minute precision
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuthToken(SQLModel, table=True):
    __tablename__ = "auth_tokens"

    token: str = Field(primary_key=True)
    device_label: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    expires_at: datetime


class UserPreference(SQLModel, table=True):
    __tablename__ = "user_preferences"

    key: str = Field(primary_key=True)
    value: str


class ResumeSnapshot(SQLModel, table=True):
    """Manual-pause state only. Rain abort writes no snapshot."""

    __tablename__ = "resume_snapshot"

    id: int = Field(default=1, primary_key=True)
    sequence_id: str
    zone_id: str
    zone_index: int
    remaining_min: float
    paused_at: datetime


class ActiveRun(SQLModel, table=True):
    """In-flight run state for crash recovery (singleton id=1).

    Written at every zone start and cleared at every *graceful* end (completion,
    stop, pause, watchdog, error). It therefore survives only a hard crash /
    abrupt process restart — exactly the case where the in-memory runner state
    and watchdog are lost while a valve may still be physically open.
    """

    __tablename__ = "active_run"

    id: int = Field(default=1, primary_key=True)
    sequence_id: str
    zone_index: int
    zone_started_at: datetime
    zone_planned_min: float  # planned duration of the current zone (for staleness/remaining)
    run_duration_min: float  # per-zone duration for the subsequent zones
    triggered_by: str


class ConfigDocument(SQLModel, table=True):
    """Full Naiad configuration persisted as a single JSON document (singleton id=1).

    The database — not config.yaml — is the source of truth once seeded. Secrets
    (ha.token, auth.password) are stripped before persistence and re-injected from
    the environment on load; they must come from environment variables only.
    """

    __tablename__ = "config_document"

    id: int = Field(default=1, primary_key=True)
    data: str  # JSON-serialized AppConfig with secret fields blanked
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SequenceOverride(SQLModel, table=True):
    """Per-sequence user overrides. NULL = use YAML default."""

    __tablename__ = "sequence_overrides"

    sequence_id: str = Field(primary_key=True)
    basis_min_per_zone: int | None = None
    watchdog_min: int | None = None
    paused: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FactorOverride(SQLModel, table=True):
    """Factor parameter overrides — singleton (id always = 1). NULL = use YAML default."""

    __tablename__ = "factor_overrides"

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
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
