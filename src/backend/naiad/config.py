import os
import re
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── HA ──────────────────────────────────────────────────────────────────────


class HAConfig(BaseModel):
    url: str
    token: str
    notify_targets: list[str] = []


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
    precipitation_prob_today: str
    precipitation_prob_tomorrow: str
    precipitation_today: str
    precipitation_tomorrow: str


# ── Zones ─────────────────────────────────────────────────────────────────────


class ZoneConfig(BaseModel):
    label: str
    switch: str
    flow_lph: float


# ── Sequences ────────────────────────────────────────────────────────────────


class ScheduleConfig(BaseModel):
    cron: str


class SequenceConfig(BaseModel):
    label: str
    zones: list[str]
    basis_min_per_zone: float
    range: tuple[float, float] = (5.0, 240.0)
    watchdog_min: int
    schedule: ScheduleConfig
    enabled: bool = True
    wind_blocks: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "SequenceConfig":
        lo, hi = self.range
        if lo >= hi:
            raise ValueError(f"range[0] must be < range[1], got [{lo}, {hi}]")
        return self


# ── Factors ──────────────────────────────────────────────────────────────────


class TempFactorConfig(BaseModel):
    formula: Literal["linear"] = "linear"
    basis_c: float = 20.0
    pct_per_c: float = 7.0
    min_pct: int = 80
    max_pct: int = 150


class RainFactorConfig(BaseModel):
    forecast_days: int = 2
    threshold_prob: int = 70
    reduce_above_mm: float = 5.0
    zero_above_mm: float = 20.0
    forecast_decay: float = Field(default=0.5, ge=0.0, le=1.0)

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


# ── Root ─────────────────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ha: HAConfig
    auth: AuthConfig = AuthConfig()
    sensors: SensorsConfig
    zones: dict[str, ZoneConfig]
    sequences: dict[str, SequenceConfig]
    factors: FactorsConfig = FactorsConfig()
    timezone: str = "Europe/Berlin"  # IANA tz for cron schedules and day bucketing

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
