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
    triggered_by: str  # cron | manual | plan | resume | mqtt
    aborted: bool = False
    abort_reason: str | None = None  # See docs/openapi.yaml: AbortReason


class DecisionLog(SQLModel, table=True):
    """Audit trail of automatic start decisions ("why did/didn't it water?").

    One row per deterministic outcome of the shared gate path
    (``run_sequence_job``: cron, plans, MQTT commands): ``started`` or
    ``skipped`` with a reason. Transient outcomes (busy/conflict) are retried
    and therefore not logged — the eventual retry produces the row. The factor
    inputs are NULL when a gate fired before the sensors were read (e.g.
    master off); ``temp_c`` is the temperature the factor actually used
    (forecast daily max, falling back to the current reading).
    """

    __tablename__ = "decision_log"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    sequence_id: str
    triggered_by: str  # cron | plan | mqtt
    decision: str  # started | skipped
    reason: str | None = None  # See docs/openapi.yaml: DecisionReason
    factor_pct: float | None = None
    temp_delta_pct: float | None = None
    rain_factor_pct: float | None = None
    temp_c: float | None = None
    rain_today_mm: float | None = None
    rain_tomorrow_mm: float | None = None
    rain_prob_today_pct: float | None = None
    rain_prob_tomorrow_pct: float | None = None
    rain_credit_mm: float | None = None
    rain_mode: str | None = None  # forecast | water_balance | et0
    # True when factor_pct came from the manual adjustment override.
    manual_factor: bool = False


class Plan(SQLModel, table=True):
    __tablename__ = "plans"

    id: str = Field(primary_key=True)  # UUID
    # Exactly one target is set: a sequence plan has sequence_id; a single-zone
    # plan has zone_id (and an empty sequence_id, since the column is NOT NULL in
    # databases created before zone_id existed).
    sequence_id: str = ""
    zone_id: str | None = None
    scheduled_at: datetime
    duration_min: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeferredCronRun(SQLModel, table=True):
    """One short-lived deferred cron occurrence per sequence.

    Safety cleanup may temporarily block a cron start. Keep at most one retry per
    sequence and expire it promptly so an outage cannot build a stale watering
    backlog that executes much later.
    """

    __tablename__ = "deferred_cron_runs"

    sequence_id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    expires_at: datetime


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
    """Manual-pause state only. Rain abort writes no snapshot.

    One row per paused sequence (keyed by ``sequence_id``) so multiple sequences
    can be paused independently while others keep running.
    """

    __tablename__ = "resume_snapshot"

    sequence_id: str = Field(primary_key=True)
    zone_id: str
    zone_index: int
    remaining_min: float
    paused_at: datetime


class ActiveRun(SQLModel, table=True):
    """In-flight run state for crash recovery (one row per running sequence).

    Written at every zone start and cleared at every controlled end (completion,
    stop, pause, watchdog, handled error). It therefore survives only a hard crash /
    abrupt process restart — exactly the case where the in-memory runner state
    and watchdog are lost while a valve may still be physically open. Keyed by
    ``sequence_id`` so several concurrent runs can each be recovered.
    """

    __tablename__ = "active_run"

    sequence_id: str = Field(primary_key=True)
    # Nullable for rows created before switch-specific crash recovery existed.
    switch: str | None = None
    zone_index: int
    zone_started_at: datetime
    zone_planned_min: float  # planned duration of the current zone (for staleness/remaining)
    run_duration_min: float  # per-zone duration for the subsequent zones
    triggered_by: str


class PendingClose(SQLModel, table=True):
    """A valve (switch entity) whose turn_off could not be confirmed.

    Keyed by the physical ``switch`` entity — not ``zone_id`` — because that is the
    thing actually left open. A config reload may remove a zone or re-point it to a
    different switch; keying by switch guarantees the retry closes *exactly* the
    entity that was commanded, a new close for a different switch never overwrites
    an old record, and clearing one switch never drops another's pending close.

    Decoupled from :class:`ActiveRun` (keyed by ``sequence_id``, holding only the
    *current* zone): a multi-zone sequence can leave several valves unconfirmed-open
    and reconciliation can fail to close a valve no run owns — both need durable,
    per-switch tracking. ``zone_id`` is retained as informational context (the zone
    that was running when the close failed) and may be stale after a reload.
    """

    __tablename__ = "pending_close"

    switch: str = Field(primary_key=True)
    zone_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    rain_mode: str | None = None
    rain_threshold_prob: int | None = None
    rain_reduce_above_mm: float | None = None
    rain_zero_above_mm: float | None = None
    rain_forecast_decay: float | None = None
    rain_water_balance_days: int | None = None
    rain_water_balance_decay: float | None = None
    rain_et0_reservoir_mm: float | None = None
    rain_peak_tomorrow: bool | None = None
    rain_confirm_with_sensor: bool | None = None
    # Manual adjustment override. When manual_mode is True the automatic
    # temp/rain/season factor is bypassed entirely and manual_pct is used as the
    # combined factor (clamped to the temperature factor's min/max bounds).
    manual_mode: bool = False
    manual_pct: int | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QueuedNotification(SQLModel, table=True):
    """A push notification buffered because Home Assistant was unreachable.

    Re-delivered on the next HA (re)connect — including after a restart, since the
    rows survive in the database. Entries older than ``notifications.queue_max_hours``
    are pruned instead of being delivered late. ``quiet``/``platform`` are stored so
    the original silent/platform payload can be rebuilt at delivery time.
    """

    __tablename__ = "queued_notifications"

    id: int | None = Field(default=None, primary_key=True)
    service: str
    message: str
    category: str
    quiet: bool = False
    platform: str = "auto"
    enqueued_at: datetime = Field(  # naive UTC, like skipped_runs
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
