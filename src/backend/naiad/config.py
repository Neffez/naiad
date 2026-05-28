import os
import re
from pathlib import Path
from typing import Literal

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


class AuthConfig(BaseModel):
    mode: Literal["password", "forward_header", "none"] = "password"
    password: str = ""  # plain text or bcrypt hash ($2b$...)
    auto_login: AutoLoginConfig = AutoLoginConfig()
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

    @model_validator(mode="after")
    def validate_zone_references(self) -> "AppConfig":
        for seq_id, seq in self.sequences.items():
            for zone_id in seq.zones:
                if zone_id not in self.zones:
                    raise ValueError(
                        f"Sequence '{seq_id}' references unknown zone '{zone_id}'"
                    )
        return self


# ── Loader ───────────────────────────────────────────────────────────────────

def _expand_env_vars(text: str) -> str:
    def replace(m: re.Match[str]) -> str:
        var = m.group(1)
        if var not in os.environ:
            raise ValueError(
                f"Config references undefined environment variable: ${{{var}}}"
            )
        return os.environ[var]

    return re.sub(r"\$\{(\w+)\}", replace, text)


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
