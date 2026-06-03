import os
import re
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── HA ──────────────────────────────────────────────────────────────────────

# The canonical set of notification kinds. Each notify target subscribes to a
# subset of these (see NotifyTarget).
NOTIFICATION_CATEGORIES: tuple[str, ...] = ("start", "skip", "abort", "reminder")


class NotifyTarget(BaseModel):
    """One push recipient (an HA ``notify.*`` service) and what it wants.

    ``categories`` selects which notification kinds this target receives, so e.g.
    one phone can get only the evening reminder while another gets everything.
    ``quiet`` asks for silent/low-priority delivery; ``platform`` tunes the silent
    payload (Android vs iOS use different keys).
    """

    service: str
    categories: list[str] = list(NOTIFICATION_CATEGORIES)
    quiet: bool = False
    platform: Literal["auto", "ios", "android"] = "auto"

    @field_validator("categories")
    @classmethod
    def _known_categories(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in NOTIFICATION_CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown notification categories: {unknown}")
        return v


def quiet_payload(platform: str) -> dict[str, Any]:
    """HA ``data`` payload requesting silent/low-priority delivery.

    Android and iOS use different keys, so ``auto`` sends both (each platform
    ignores the other's): Android → a low-importance channel (no sound); iOS → a
    passive interruption level with no sound.
    """
    data: dict[str, Any] = {}
    if platform in ("auto", "android"):
        data["importance"] = "low"
    if platform in ("auto", "ios"):
        data["push"] = {"sound": "none", "interruption-level": "passive"}
    return data


def target_service_data(target: "NotifyTarget", message: str) -> dict[str, Any]:
    service_data: dict[str, Any] = {"message": message}
    if target.quiet:
        service_data["data"] = quiet_payload(target.platform)
    return service_data


class MQTTConfig(BaseModel):
    """Optional MQTT bridge that publishes irrigation statistics to Home Assistant.

    When ``enabled`` and a broker ``host`` is set, Naiad publishes its tracked
    liters and run durations as MQTT-discovery sensors. Home Assistant then exposes
    them as native entities (with long-term statistics) and — via its InfluxDB
    integration — forwards their state changes to InfluxDB/Grafana.

    The ``password`` is environment-managed like other secrets: it is stripped
    before the config is persisted and re-injected from ``MQTT_PASSWORD`` on load.
    """

    enabled: bool = False
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    client_id: str = "naiad"
    # HA MQTT-discovery prefix (matches the broker/HA configuration; almost always
    # the default "homeassistant").
    discovery_prefix: str = "homeassistant"
    # Root topic for Naiad's own state/availability topics.
    base_topic: str = "naiad"


class HAConfig(BaseModel):
    url: str
    token: str
    notify_targets: list[NotifyTarget] = []

    @field_validator("notify_targets", mode="before")
    @classmethod
    def _coerce_targets(cls, v: object) -> object:
        # Back-compat: a plain list of service strings becomes targets that
        # receive every category (the previous behaviour).
        if isinstance(v, list):
            return [{"service": x} if isinstance(x, str) else x for x in v]
        return v


# ── Auth ─────────────────────────────────────────────────────────────────────


class AutoLoginTrigger(BaseModel):
    url_param: str = "embed"
    trusted_referers: list[str] = []
    trusted_ips: list[str] = []


class AutoLoginConfig(BaseModel):
    enabled: bool = False
    trigger: AutoLoginTrigger = AutoLoginTrigger()


class ForwardHeaderConfig(BaseModel):
    """Trusted reverse-proxy header auth (mode = forward_header)."""

    header: str = "X-Forwarded-User"
    # If non-empty, the request's client IP must be one of these (the proxy).
    trusted_proxies: list[str] = []


class IngressConfig(BaseModel):
    """Home Assistant ingress trust.

    When enabled, requests proxied by the Supervisor ingress are treated as already
    authenticated by Home Assistant — no Naiad login is needed for the sidebar.
    This rule is additive: it coexists with the configured ``mode`` so the direct
    port (which does not pass through HA auth) still requires a password.
    """

    enabled: bool = True
    # The Supervisor's fixed internal IP for the ingress proxy. A LAN client cannot
    # forge this source address over TCP, which is what makes the trust safe.
    trusted_ip: str = "172.30.32.2"


class AuthConfig(BaseModel):
    mode: Literal["password", "forward_header", "none"] = "password"
    password: str = ""  # plain text or bcrypt hash ($2b$...)
    forward_header: ForwardHeaderConfig = ForwardHeaderConfig()
    auto_login: AutoLoginConfig = AutoLoginConfig()
    ingress: IngressConfig = IngressConfig()
    frame_ancestors: list[str] = ["'self'"]


# ── Sensors ──────────────────────────────────────────────────────────────────


class SensorsConfig(BaseModel):
    rain: str
    wind: str
    season: str
    temperature: str
    # Optional forecast of the day's maximum temperature. When set it is used for
    # the temperature adjustment instead of the current temperature, so a run
    # scheduled at night still scales to the (warmer) daytime peak. Empty = fall
    # back to the current temperature sensor.
    temperature_max: str = ""
    precipitation_prob_today: str
    precipitation_prob_tomorrow: str
    precipitation_today: str
    precipitation_tomorrow: str
    # Optional actual precipitation amount sensor. Naiad reads its HA recorder
    # history and turns recent positive deltas into a multi-day rain credit for
    # the water-balance rain mode. Works with daily-reset or total-increasing mm
    # sensors as long as state changes are numeric.
    precipitation_actual: str = ""


# ── Zones ─────────────────────────────────────────────────────────────────────


# Some valve actuators (e.g. KNX switch actuators) offer a hardware "staircase
# light" timer: a turn-on keeps the switch on for a fixed time and then closes it
# on its own, bounding how long a valve can stay open if a turn-off is ever lost.
# When enabled for a zone, Naiad re-sends "on" before that timer expires so the
# valve stays open for the full watering, while the actuator still acts as a
# hardware safety net. The re-trigger interval is derived (no benefit to making it
# configurable): re-trigger at half the actuator timer, which tolerates a single
# missed/failed trigger without the valve dropping.
STAIRCASE_RETRIGGER_FRACTION = 0.5
# On a failed re-trigger (HA hiccup), retry sooner than the normal interval — we
# still have until the actuator's timer elapses to land a successful "on".
STAIRCASE_RETRY_ON_FAILURE_S = 5.0


class ZoneConfig(BaseModel):
    label: str
    switch: str
    flow_lph: float = Field(gt=0)
    # Hardware staircase-light timer support (see note above). When enabled,
    # ``staircase_min`` is the actuator's configured on-time in minutes.
    staircase_enabled: bool = False
    staircase_min: float = 0.0

    @model_validator(mode="after")
    def _validate_staircase(self) -> "ZoneConfig":
        if self.staircase_enabled and self.staircase_min <= 0:
            raise ValueError("staircase_min must be > 0 when staircase_enabled is true")
        return self


def staircase_retrigger_interval_min(zone: ZoneConfig) -> float | None:
    """The interval (minutes) at which to re-send "on" for a staircase zone, or
    None when the zone does not use the actuator's staircase timer."""
    if not zone.staircase_enabled or zone.staircase_min <= 0:
        return None
    return zone.staircase_min * STAIRCASE_RETRIGGER_FRACTION


# ── Sequences ────────────────────────────────────────────────────────────────


# Day-of-week mapping between ISO weekday numbers (1=Mon … 7=Sun, used by the
# UI and stored in config) and the lowercase names APScheduler understands.
# Names are emitted in generated cron strings so the schedule is unambiguous,
# regardless of the 0=Sun vs 0=Mon convention confusion around numeric crons.
_ISO_BY_NAME = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
_NAME_BY_ISO = {iso: name for name, iso in _ISO_BY_NAME.items()}
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_MAX_TIMES = 5


def _parse_dow_names(field: str) -> list[int] | None:
    """Parse a cron day-of-week field into ISO weekday numbers (1=Mon … 7=Sun).

    Only the unambiguous forms are accepted: ``*`` (every day) and name-based
    tokens (``mon``, ``mon-fri``, ``mon,wed,fri``). Numeric tokens are rejected
    (return ``None``) because the 0=Sun/0=Mon convention is ambiguous — such
    expressions are kept verbatim as an advanced cron override instead.
    """
    field = field.strip().lower()
    if field == "*":
        return []
    out: set[int] = set()
    for token in field.split(","):
        token = token.strip()
        if "-" in token:
            lo_name, _, hi_name = token.partition("-")
            if lo_name not in _ISO_BY_NAME or hi_name not in _ISO_BY_NAME:
                return None
            lo, hi = _ISO_BY_NAME[lo_name], _ISO_BY_NAME[hi_name]
            if lo > hi:
                return None
            out.update(range(lo, hi + 1))
        elif token in _ISO_BY_NAME:
            out.add(_ISO_BY_NAME[token])
        else:
            return None
    return sorted(out)


def parse_simple_cron(expr: str) -> tuple[list[int], str] | None:
    """Convert a cron expression into ``(days, "HH:MM")`` if it represents a
    single daily time on whole-day-of-week selection, else ``None``."""
    parts = expr.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if dom != "*" or month != "*":
        return None
    if not (minute.isdigit() and hour.isdigit()):
        return None
    m, h = int(minute), int(hour)
    if not (0 <= m < 60 and 0 <= h < 24):
        return None
    days = _parse_dow_names(dow)
    if days is None:
        return None
    return days, f"{h:02d}:{m:02d}"


def cron_for_time(time_str: str, days: list[int]) -> str:
    """Build a cron expression firing at ``time_str`` (HH:MM) on the given ISO
    weekdays (empty = every day)."""
    hh, _, mm = time_str.partition(":")
    dow = ",".join(_NAME_BY_ISO[d] for d in sorted(set(days))) if days else "*"
    return f"{int(mm)} {int(hh)} * * {dow}"


class ScheduleConfig(BaseModel):
    """When a sequence runs automatically.

    Expressed as a list of clock times on a set of weekdays — the friendly form
    the UI edits. ``cron`` is an advanced escape hatch: when set it overrides
    ``days``/``times`` and is used verbatim, for expressions the picker can't
    represent (e.g. interval schedules).
    """

    days: list[int] = Field(default_factory=list)  # ISO 1=Mon … 7=Sun; empty = every day
    times: list[str] = Field(default_factory=list)  # "HH:MM", up to _MAX_TIMES
    cron: str | None = None  # advanced override; takes precedence when set

    @model_validator(mode="after")
    def _normalize(self) -> "ScheduleConfig":
        # Migrate a simple/legacy cron into the picker model so the UI can edit
        # it; keep anything the picker can't represent as an advanced override.
        if self.cron and not self.times:
            parsed = parse_simple_cron(self.cron.strip())
            if parsed is not None:
                self.days, time = parsed
                self.times = [time]
                self.cron = None
        if self.cron is not None and not self.cron.strip():
            self.cron = None

        normalized: list[str] = []
        for raw in self.times:
            match = _TIME_RE.match(raw.strip())
            if match is None:
                raise ValueError(f"Invalid time {raw!r}, expected HH:MM")
            candidate = f"{int(match.group(1)):02d}:{match.group(2)}"
            if candidate not in normalized:
                normalized.append(candidate)
        if len(normalized) > _MAX_TIMES:
            raise ValueError(f"At most {_MAX_TIMES} times per schedule")
        self.times = normalized

        for day in self.days:
            if not 1 <= day <= 7:
                raise ValueError(f"Invalid weekday {day}, expected 1..7")
        self.days = sorted(set(self.days))
        return self

    def to_crons(self) -> list[str]:
        """The cron expressions to register — one trigger per clock time, or the
        single advanced override when set."""
        if self.cron:
            return [self.cron]
        return [cron_for_time(t, self.days) for t in self.times]


# Accent-color keys for the colored bar on a sequence card. The hex values
# behind each key live in the frontend palette (src/frontend/src/theme/
# sequenceColors.ts); the backend only stores/validates the key. None means no
# explicit choice (a neutral default bar is shown when colors are enabled).
SequenceColor = Literal["green", "sand", "purple", "slate", "blue", "rose"]


class SequenceConfig(BaseModel):
    label: str
    zones: list[str]
    basis_min_per_zone: float = Field(gt=0)
    range: tuple[float, float] = (5.0, 240.0)
    watchdog_min: int = Field(gt=0)
    schedule: ScheduleConfig
    enabled: bool = True
    wind_blocks: bool = False
    color: SequenceColor | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "SequenceConfig":
        lo, hi = self.range
        if lo < 0:
            raise ValueError(f"range[0] must be >= 0, got {lo}")
        if lo >= hi:
            raise ValueError(f"range[0] must be < range[1], got [{lo}, {hi}]")
        return self


# ── Factors ──────────────────────────────────────────────────────────────────


class TempFactorConfig(BaseModel):
    formula: Literal["linear"] = "linear"
    basis_c: float = 20.0
    pct_per_c: float = 7.0
    min_pct: int = Field(default=80, ge=0)
    max_pct: int = Field(default=150, ge=0)

    @model_validator(mode="after")
    def validate_pct_bounds(self) -> "TempFactorConfig":
        if self.min_pct > self.max_pct:
            raise ValueError(f"min_pct ({self.min_pct}) must be <= max_pct ({self.max_pct})")
        return self


class RainFactorConfig(BaseModel):
    mode: Literal["forecast", "water_balance"] = "forecast"
    forecast_days: int = Field(default=2, ge=1)
    threshold_prob: int = Field(default=70, ge=0, le=100)
    reduce_above_mm: float = 5.0
    zero_above_mm: float = 20.0
    forecast_decay: float = Field(default=0.5, ge=0.0, le=1.0)
    water_balance_days: int = Field(default=4, ge=1, le=14)
    water_balance_decay: float = Field(default=0.65, ge=0.0, le=1.0)
    # When True the rain factor also uses the day's *peak* forecast for tomorrow
    # (the highest value seen since local midnight), not just the latest reading —
    # mirroring how today is handled. Today always uses the peak; tomorrow's
    # forecast is more volatile, so peaking it is opt-in. False = today only.
    peak_tomorrow: bool = False
    # When True today's peak forecast only counts if the binary rain sensor
    # (``sensors.rain``) actually fired at some point today; otherwise today falls
    # back to the latest reading. This stops a forecast spike that never produced
    # real rain from suppressing irrigation all day. Only meaningful for *today*
    # (tomorrow has not happened yet). Opt-in so a noisy/misconfigured rain sensor
    # can't silently reduce suppression. False = today always uses the peak.
    confirm_with_rain_sensor: bool = False

    @model_validator(mode="after")
    def validate_mm_thresholds(self) -> "RainFactorConfig":
        if self.reduce_above_mm >= self.zero_above_mm:
            raise ValueError(
                f"reduce_above_mm ({self.reduce_above_mm}) must be "
                f"< zero_above_mm ({self.zero_above_mm})"
            )
        return self


class FactorsConfig(BaseModel):
    temp: TempFactorConfig = TempFactorConfig()
    rain: RainFactorConfig = RainFactorConfig()


# ── Notifications ──────────────────────────────────────────────────────────────


class NotificationsConfig(BaseModel):
    """Global notification settings. Per-recipient choices (which categories, quiet,
    platform) live on each :class:`NotifyTarget`."""

    evening_reminder_cron: str = "0 21 * * *"  # when the nightly reminder is sent
    # When Home Assistant is unreachable, notifications that could not be sent are
    # queued and re-delivered on reconnect. Items older than this many hours are
    # dropped instead of arriving late. 0 disables queuing (failed sends are dropped
    # immediately, the previous behaviour).
    queue_max_hours: float = 6.0

    @field_validator("queue_max_hours")
    @classmethod
    def _non_negative_max_hours(cls, v: float) -> float:
        if v < 0:
            raise ValueError("queue_max_hours must be >= 0")
        return v


# ── Root ─────────────────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ha: HAConfig
    mqtt: MQTTConfig = MQTTConfig()
    auth: AuthConfig = AuthConfig()
    sensors: SensorsConfig
    zones: dict[str, ZoneConfig]
    sequences: dict[str, SequenceConfig]
    factors: FactorsConfig = FactorsConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    timezone: str = "Europe/Berlin"  # IANA tz for cron schedules and day bucketing
    language: Literal["de", "en"] = "en"  # language of server-side notifications
    # Global switch for the colored accent bars on sequence cards. When false, no
    # bars are shown anywhere regardless of per-sequence color choices.
    sequence_colors_enabled: bool = True

    @model_validator(mode="after")
    def validate_timezone(self) -> "AppConfig":
        from zoneinfo import ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Invalid timezone: {self.timezone!r}") from e
        return self

    @model_validator(mode="after")
    def validate_zone_references(self) -> "AppConfig":
        for seq_id, seq in self.sequences.items():
            for zone_id in seq.zones:
                if zone_id not in self.zones:
                    raise ValueError(f"Sequence '{seq_id}' references unknown zone '{zone_id}'")
        return self

    @model_validator(mode="after")
    def validate_unique_switches(self) -> "AppConfig":
        """Each switch entity must belong to exactly one zone.

        Zone reservation and valve ownership are tracked by switch entity, so two
        zones sharing a switch could run in parallel and physically fight over the
        same valve. Forbid the ambiguity at config time.
        """
        seen: dict[str, str] = {}
        for zone_id, zone in self.zones.items():
            # An empty switch means "not yet configured" — these are allowed in any
            # number (a run on such a zone is rejected separately at start time) and
            # are not a physical entity, so they never collide.
            if not zone.switch:
                continue
            if zone.switch in seen:
                raise ValueError(
                    f"Zones '{seen[zone.switch]}' and '{zone_id}' share switch "
                    f"'{zone.switch}'; each switch must map to exactly one zone"
                )
            seen[zone.switch] = zone_id
        return self


# ── Home Assistant add-on context ─────────────────────────────────────────────

# When Naiad runs as a Home Assistant add-on, the Supervisor reaches Core through
# an internal proxy and injects a short-lived token, so no long-lived access token
# is needed (and none should be configured).
SUPERVISOR_WS_URL = "ws://supervisor/core/websocket"


def is_addon_context() -> bool:
    """True when running as a Supervisor-managed Home Assistant add-on.

    The Supervisor always injects ``SUPERVISOR_TOKEN`` into add-on containers; its
    presence is the canonical signal that we are running inside the add-on.
    """
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def resolve_ha_connection(url: str, token: str) -> tuple[str, str]:
    """Resolve the effective HA WebSocket URL and access token.

    In the add-on context, reach Core via the Supervisor proxy
    (``ws://supervisor/core/websocket``) using the auto-provided
    ``SUPERVISOR_TOKEN`` — the manual long-lived token is not required. Outside the
    add-on (standalone container / LXC), the configured values from the database or
    environment are used unchanged.
    """
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if supervisor_token:
        return SUPERVISOR_WS_URL, supervisor_token
    return url, token


# ── Loader ───────────────────────────────────────────────────────────────────


_REQUIRED_CONFIG_VARS = {"HA_TOKEN"}


def _expand_env_vars(text: str) -> str:
    missing: list[str] = []

    def replace(m: re.Match[str]) -> str:
        var = m.group(1)
        if var in os.environ:
            return os.environ[var]
        if var in _REQUIRED_CONFIG_VARS:
            missing.append(var)
        return ""

    result = re.sub(r"\$\{(\w+)\}", replace, text)
    if missing:
        raise ValueError(
            "Config references required environment variable(s) that are not set: "
            + ", ".join(f"${{{v}}}" for v in missing)
        )
    return result


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        path = Path(os.environ.get("NAIAD_CONFIG", "/data/config.yaml"))

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to your data directory and adjust it."
        )

    raw = path.read_text(encoding="utf-8")
    expanded = _expand_env_vars(raw)
    data = yaml.safe_load(expanded)
    return AppConfig.model_validate(data)
