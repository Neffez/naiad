import copy

import pytest
from pydantic import ValidationError

from naiad.config import (
    SUPERVISOR_WS_URL,
    AppConfig,
    is_addon_context,
    resolve_ha_connection,
)
from tests.conftest import MINIMAL_CONFIG_DATA


def test_valid_config_loads(minimal_config: AppConfig) -> None:
    assert minimal_config.ha.url == "ws://localhost:8123/api/websocket"
    assert "zone_a" in minimal_config.zones
    assert "seq_1" in minimal_config.sequences


def test_sequence_zone_list(minimal_config: AppConfig) -> None:
    assert minimal_config.sequences["seq_1"].zones == ["zone_a"]


def test_wind_blocks_flag(minimal_config: AppConfig) -> None:
    assert minimal_config.sequences["seq_wind"].wind_blocks is True


def test_unknown_zone_reference_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["sequences"]["seq_1"]["zones"] = ["does_not_exist"]
    with pytest.raises(ValidationError, match="does_not_exist"):
        AppConfig.model_validate(data)


@pytest.mark.parametrize("bad_flow", [0, -1, -500.0])
def test_non_positive_flow_lph_rejected(bad_flow: float) -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["zones"]["zone_a"]["flow_lph"] = bad_flow
    with pytest.raises(ValidationError, match="flow_lph"):
        AppConfig.model_validate(data)


@pytest.mark.parametrize("field", ["watchdog_min", "basis_min_per_zone"])
@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_sequence_runtimes_rejected(field: str, bad: int) -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["sequences"]["seq_1"][field] = bad
    with pytest.raises(ValidationError, match=field):
        AppConfig.model_validate(data)


def test_negative_range_lower_bound_rejected() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["sequences"]["seq_1"]["range"] = [-1.0, 240.0]
    with pytest.raises(ValidationError, match="range"):
        AppConfig.model_validate(data)


def test_missing_ha_token_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    del data["ha"]["token"]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_missing_sensor_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    del data["sensors"]["rain"]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_invalid_range_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["sequences"]["seq_1"]["range"] = [60, 30]  # lo > hi
    with pytest.raises(ValidationError, match="range"):
        AppConfig.model_validate(data)


def test_factor_defaults(minimal_config: AppConfig) -> None:
    assert minimal_config.factors.temp.basis_c == 20.0
    assert minimal_config.factors.temp.min_pct == 80
    assert minimal_config.factors.rain.forecast_decay == 0.5
    assert minimal_config.factors.rain.zero_above_mm > minimal_config.factors.rain.reduce_above_mm


def test_extra_fields_rejected() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["unknown_key"] = "value"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_temp_min_pct_above_max_pct_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["factors"] = {"temp": {"min_pct": 200, "max_pct": 80}}
    with pytest.raises(ValidationError, match="min_pct"):
        AppConfig.model_validate(data)


def test_threshold_prob_out_of_range_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["factors"] = {"rain": {"threshold_prob": 150}}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


# ── Add-on / Supervisor context ───────────────────────────────────────────────


def test_resolve_ha_connection_standalone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    url, token = resolve_ha_connection("ws://configured:8123/api/websocket", "llat-token")
    assert url == "ws://configured:8123/api/websocket"
    assert token == "llat-token"
    assert is_addon_context() is False


def test_resolve_ha_connection_addon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    url, token = resolve_ha_connection("ws://configured:8123/api/websocket", "llat-token")
    assert url == SUPERVISOR_WS_URL
    assert token == "supervisor-secret"
    assert is_addon_context() is True


# ── Notify targets (per-recipient) ────────────────────────────────────────────


def test_notify_target_string_coercion() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["ha"]["notify_targets"] = ["notify.a"]
    cfg = AppConfig.model_validate(data)
    t = cfg.ha.notify_targets[0]
    assert t.service == "notify.a"
    assert set(t.categories) == {"start", "skip", "abort", "reminder"}  # all by default
    assert t.quiet is False and t.platform == "auto"


def test_notify_target_unknown_category_raises() -> None:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["ha"]["notify_targets"] = [{"service": "notify.a", "categories": ["bogus"]}]
    with pytest.raises(ValidationError, match="categories"):
        AppConfig.model_validate(data)
