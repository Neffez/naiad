from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from naiad.config import (
    AutoLoginConfig,
    FactorsConfig,
    ForwardHeaderConfig,
    NotificationsConfig,
    NotifyTarget,
    SensorsConfig,
    SequenceConfig,
    ZoneConfig,
)


def _serialize_utc(dt: datetime) -> str:
    """Serialize a datetime as an explicit-UTC ISO 8601 string.

    Timestamps are stored as *naive* UTC (SQLModel strips tzinfo), so without
    this they would be emitted without an offset and parsed as local time by the
    browser. Tagging them as UTC lets the frontend convert to local correctly.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


# Use for every datetime returned to clients so the wire format is unambiguous UTC.
UtcDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str)]

# ── Auth ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str
    device_label: str | None = None


class AutoLoginRequest(BaseModel):
    embed_param_present: bool
    device_label: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: UtcDatetime


class AuthTokenResponse(BaseModel):
    token_prefix: str
    device_label: str | None
    created_at: UtcDatetime
    last_used_at: UtcDatetime | None
    expires_at: UtcDatetime


# ── Sequences ─────────────────────────────────────────────────────────────────


class StartSequenceRequest(BaseModel):
    duration_min: int | None = Field(default=None, gt=0)


class StartZoneRequest(BaseModel):
    duration_min: int = Field(gt=0)


class ZoneSummaryResponse(BaseModel):
    id: str
    label: str
    valve_state: str


class CurrentRunResponse(BaseModel):
    zone_id: str
    zone_label: str
    started_at: UtcDatetime
    elapsed_min: float
    remaining_min: float
    total_min: float
    triggered_by: str


class FactorNotesResponse(BaseModel):
    """Structured reasons behind a sequence's current factor.

    Kept machine-readable so the frontend can localize; the backend never emits
    user-facing prose (see CLAUDE.md i18n rule).
    """

    season_off: bool = False
    wind_blocked: bool = False
    rain_factor_pct: int | None = None  # set only when rain reduces watering (<100)
    temp_delta_pct: int | None = None  # signed; set only when |delta| >= 5


class ScheduleSummaryResponse(BaseModel):
    days: list[int]  # ISO weekdays 1=Mon … 7=Sun; empty = every day
    times: list[str]  # "HH:MM"
    cron: str | None = None  # set only when an advanced cron override is active


class SequenceStateResponse(BaseModel):
    id: str
    label: str
    status: str
    enabled: bool
    paused: bool
    factor_pct: int
    factor_notes: FactorNotesResponse
    schedule: ScheduleSummaryResponse
    next_run_at: UtcDatetime | None
    zones: list[ZoneSummaryResponse]
    basis_min_per_zone: int
    current_run: CurrentRunResponse | None


# ── System status ─────────────────────────────────────────────────────────────


class WeatherSummaryResponse(BaseModel):
    temp_c: float | None
    rain_24h_mm: float
    wind_label: str
    season_active: bool


class FactorBreakdownResponse(BaseModel):
    # Both are signed deltas from the neutral baseline (0 = no adjustment):
    # temp_pct = temperature contribution, rain_pct = rain contribution.
    temp_pct: int
    rain_pct: int
    combined_pct: int  # overall factor as a percentage (100 = neutral)
    # True when combined_pct comes from a manual override; the temp/rain deltas
    # above are neutral (0) in that case and should not be shown as a breakdown.
    manual: bool = False
    wind_blocking_sequences: list[str]
    # Sensor inputs used in the factor calculation, for UI traceability.
    temp_input_c: float | None = None
    rain_prob_pct: float | None = None
    rain_mm: float | None = None


class NextRunResponse(BaseModel):
    sequence_id: str
    sequence_label: str
    scheduled_at: UtcDatetime
    duration_min: int
    # Set for one-off planned runs; the skip endpoint deletes the plan directly.
    # None for recurring cron runs, which are skipped via a SkippedRun record.
    plan_id: str | None = None
    # True when this entry is the run currently executing (started, not upcoming).
    # The UI marks it as live and hides the skip action.
    in_progress: bool = False


class SystemStatusResponse(BaseModel):
    master_on: bool
    ha_connected: bool
    weather: WeatherSummaryResponse
    today_factor: FactorBreakdownResponse
    next_run: NextRunResponse | None
    after_next: NextRunResponse | None
    # Upcoming (not-yet-started) runs: today's remaining runs plus all runs of the
    # next future day that has any. Spans at most two calendar days (today + next),
    # or one day if nothing remains today. Currently-running runs are excluded —
    # they are shown live on the sequence/zone cards instead.
    upcoming_runs: list[NextRunResponse]
    liters_today: float
    liters_week: float
    week_series: list[float]  # liters per local weekday Mon..Sun of the current week


class MasterToggleRequest(BaseModel):
    on: bool


class SkipRunRequest(BaseModel):
    sequence_id: str
    scheduled_at: datetime
    plan_id: str | None = None


class ValveStateResponse(BaseModel):
    id: str
    zone_id: str
    label: str
    state: str
    on_since: UtcDatetime | None
    runtime_min: float | None
    # Total planned duration of a standalone single-zone run, so the UI can show
    # remaining time (e.g. "5 / 10 min"). None unless single_run is True.
    total_min: float | None = None
    # True when this zone is currently running as a standalone single-zone run
    # (started directly, not as part of a sequence) — so the UI can offer a stop.
    single_run: bool = False


# ── History ───────────────────────────────────────────────────────────────────


class HistoryEntryResponse(BaseModel):
    id: int
    zone_id: str
    zone_label: str
    sequence_id: str
    sequence_label: str
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    duration_min: float | None
    liters: float | None
    triggered_by: str
    aborted: bool
    abort_reason: str | None


class PaginatedHistoryResponse(BaseModel):
    items: list[HistoryEntryResponse]
    total: int
    page: int
    per_page: int


class DeleteHistoryResponse(BaseModel):
    deleted: int  # number of run-history rows removed


# ── Plans ─────────────────────────────────────────────────────────────────────


class CreatePlanRequest(BaseModel):
    # Exactly one target must be provided: a sequence plan (sequence_id) or a
    # single-zone plan (zone_id, which requires duration_min).
    sequence_id: str | None = None
    zone_id: str | None = None
    mode: str  # in_hours | at_datetime
    value: float | str
    duration_min: int | None = Field(default=None, gt=0)


class PlanResponse(BaseModel):
    id: str
    target_type: Literal["sequence", "zone"]
    sequence_id: str | None
    sequence_label: str | None
    zone_id: str | None
    zone_label: str | None
    label: str  # unified display label (sequence or zone)
    scheduled_at: UtcDatetime
    duration_min: int | None
    estimated_liters: float | None
    created_at: UtcDatetime


# ── Settings ──────────────────────────────────────────────────────────────────


class TempFactorSettingsInput(BaseModel):
    basis_c: float | None = None
    pct_per_c: float | None = None
    min_pct: int | None = None
    max_pct: int | None = None


class RainFactorSettingsInput(BaseModel):
    forecast_days: int | None = None
    threshold_prob: int | None = None
    reduce_above_mm: float | None = None
    zero_above_mm: float | None = None
    forecast_decay: float | None = None
    peak_tomorrow: bool | None = None
    confirm_with_rain_sensor: bool | None = None


class FactorSettingsInput(BaseModel):
    temp: TempFactorSettingsInput | None = None
    rain: RainFactorSettingsInput | None = None
    manual_mode: bool | None = None
    manual_pct: int | None = None


class SequenceOverrideInput(BaseModel):
    basis_min_per_zone: int | None = None
    watchdog_min: int | None = None
    paused: bool | None = None


class UpdateSettingsRequest(BaseModel):
    sequences: dict[str, SequenceOverrideInput] | None = None
    factors: FactorSettingsInput | None = None
    # Bounded so a login can't mint an already-expired token (<= 0) or one that
    # effectively never expires. 365 days is the documented upper limit.
    token_lifetime_days: int | None = Field(default=None, gt=0, le=365)
    auto_login_enabled: bool | None = None


class TempFactorSettingsResponse(BaseModel):
    basis_c: float
    pct_per_c: float
    min_pct: int
    max_pct: int


class RainFactorSettingsResponse(BaseModel):
    forecast_days: int
    threshold_prob: int
    reduce_above_mm: float
    zero_above_mm: float
    forecast_decay: float
    peak_tomorrow: bool
    confirm_with_rain_sensor: bool


class SequenceOverrideResponse(BaseModel):
    basis_min_per_zone: int | None
    watchdog_min: int | None
    paused: bool


class FactorSettingsResponse(BaseModel):
    temp: TempFactorSettingsResponse
    rain: RainFactorSettingsResponse
    manual_mode: bool = False
    manual_pct: int | None = None


class AppSettingsResponse(BaseModel):
    sequences: dict[str, SequenceOverrideResponse]
    factors: FactorSettingsResponse
    token_lifetime_days: int
    auto_login_enabled: bool


# ── Preferences ───────────────────────────────────────────────────────────────


class UserPreferencesResponse(BaseModel):
    theme: str
    language: str
    sequence_order: list[str]
    zone_order: list[str]


class UpdatePreferencesRequest(BaseModel):
    theme: str | None = None
    language: str | None = None
    sequence_order: list[str] | None = None
    zone_order: list[str] | None = None


# ── Configuration ───────────────────────────────────────────────────────────────


class HAConfigPublic(BaseModel):
    """HA connection without the secret token."""

    url: str
    notify_targets: list[NotifyTarget] = []


class MQTTConfigResponse(BaseModel):
    """MQTT statistics-bridge settings without the secret password."""

    enabled: bool
    host: str
    port: int
    username: str
    client_id: str
    discovery_prefix: str
    base_topic: str
    password_set: bool  # whether a password is configured (the value is never exposed)


class MQTTConfigInput(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 1883
    username: str = ""
    client_id: str = "naiad"
    discovery_prefix: str = "homeassistant"
    base_topic: str = "naiad"


class AuthConfigResponse(BaseModel):
    mode: Literal["password", "forward_header", "none"]
    forward_header: ForwardHeaderConfig
    auto_login: AutoLoginConfig
    frame_ancestors: list[str]
    password_set: bool  # whether a password is configured (the value is never exposed)


class AuthConfigInput(BaseModel):
    mode: Literal["password", "forward_header", "none"] = "password"
    forward_header: ForwardHeaderConfig = ForwardHeaderConfig()
    auto_login: AutoLoginConfig = AutoLoginConfig()
    frame_ancestors: list[str] = ["'self'"]


class ConfigResponse(BaseModel):
    ha: HAConfigPublic
    mqtt: MQTTConfigResponse
    auth: AuthConfigResponse
    sensors: SensorsConfig
    zones: dict[str, ZoneConfig]
    sequences: dict[str, SequenceConfig]
    factors: FactorsConfig
    notifications: NotificationsConfig
    timezone: str
    sequence_colors_enabled: bool = True
    # True after an update that changed ha.url/token: the live HA socket is not
    # reconnected automatically, so a restart is needed for the connection change.
    restart_required: bool = False


class ConfigUpdateRequest(BaseModel):
    ha: HAConfigPublic
    mqtt: MQTTConfigInput = MQTTConfigInput()
    auth: AuthConfigInput
    sensors: SensorsConfig
    zones: dict[str, ZoneConfig]
    sequences: dict[str, SequenceConfig]
    factors: FactorsConfig
    notifications: NotificationsConfig = NotificationsConfig()
    timezone: str = "Europe/Berlin"
    sequence_colors_enabled: bool = True


class EntityInfo(BaseModel):
    entity_id: str
    friendly_name: str | None
    state: str
    domain: str


class EntitiesResponse(BaseModel):
    entities: list[EntityInfo]


class ServicesResponse(BaseModel):
    services: list[str]
