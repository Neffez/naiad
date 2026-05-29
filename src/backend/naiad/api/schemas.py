from datetime import datetime

from pydantic import BaseModel

# ── Auth ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str
    device_label: str | None = None


class AutoLoginRequest(BaseModel):
    embed_param_present: bool
    device_label: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime


class AuthTokenResponse(BaseModel):
    token_prefix: str
    device_label: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


# ── Sequences ─────────────────────────────────────────────────────────────────


class StartSequenceRequest(BaseModel):
    duration_min: int | None = None


class ZoneSummaryResponse(BaseModel):
    id: str
    label: str
    valve_state: str


class CurrentRunResponse(BaseModel):
    zone_id: str
    zone_label: str
    started_at: datetime
    elapsed_min: float
    remaining_min: float
    total_min: float
    triggered_by: str


class SequenceStateResponse(BaseModel):
    id: str
    label: str
    status: str
    enabled: bool
    paused: bool
    factor_pct: int
    factor_note: str | None
    schedule_label: str
    next_run_at: datetime | None
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
    temp_pct: int
    rain_pct: int
    combined_pct: int
    wind_blocking_sequences: list[str]


class NextRunResponse(BaseModel):
    sequence_id: str
    sequence_label: str
    scheduled_at: datetime
    duration_min: int


class SystemStatusResponse(BaseModel):
    master_on: bool
    ha_connected: bool
    weather: WeatherSummaryResponse
    today_factor: FactorBreakdownResponse
    next_run: NextRunResponse | None
    after_next: NextRunResponse | None
    liters_today: float
    liters_week: float
    week_series: list[float]  # liters per local weekday Mon..Sun of the current week


class MasterToggleRequest(BaseModel):
    on: bool


class ValveStateResponse(BaseModel):
    id: str
    zone_id: str
    label: str
    state: str
    on_since: datetime | None
    runtime_min: float | None


# ── History ───────────────────────────────────────────────────────────────────


class HistoryEntryResponse(BaseModel):
    id: int
    zone_id: str
    zone_label: str
    sequence_id: str
    sequence_label: str
    started_at: datetime
    ended_at: datetime | None
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


# ── Plans ─────────────────────────────────────────────────────────────────────


class CreatePlanRequest(BaseModel):
    sequence_id: str
    mode: str  # in_hours | at_datetime
    value: float | str
    duration_min: int | None = None


class PlanResponse(BaseModel):
    id: str
    sequence_id: str
    sequence_label: str
    scheduled_at: datetime
    duration_min: int | None
    estimated_liters: float | None
    created_at: datetime


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


class FactorSettingsInput(BaseModel):
    temp: TempFactorSettingsInput | None = None
    rain: RainFactorSettingsInput | None = None


class SequenceOverrideInput(BaseModel):
    basis_min_per_zone: int | None = None
    watchdog_min: int | None = None
    paused: bool | None = None


class UpdateSettingsRequest(BaseModel):
    sequences: dict[str, SequenceOverrideInput] | None = None
    factors: FactorSettingsInput | None = None
    token_lifetime_days: int | None = None
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


class SequenceOverrideResponse(BaseModel):
    basis_min_per_zone: int | None
    watchdog_min: int | None
    paused: bool


class FactorSettingsResponse(BaseModel):
    temp: TempFactorSettingsResponse
    rain: RainFactorSettingsResponse


class AppSettingsResponse(BaseModel):
    sequences: dict[str, SequenceOverrideResponse]
    factors: FactorSettingsResponse
    token_lifetime_days: int
    auto_login_enabled: bool


# ── Preferences ───────────────────────────────────────────────────────────────


class UserPreferencesResponse(BaseModel):
    theme: str
    language: str


class UpdatePreferencesRequest(BaseModel):
    theme: str | None = None
    language: str | None = None
