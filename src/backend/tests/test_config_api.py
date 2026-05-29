import pytest
from pydantic import ValidationError

from naiad.api.config import build_config_response, build_validated_config
from naiad.config import AppConfig
from naiad.config_store import to_export_dict
from naiad.ha_client import HAClient

# ── build_config_response (redaction) ─────────────────────────────────────────


def test_response_redacts_token_and_reports_password_flag(minimal_config: AppConfig) -> None:
    resp = build_config_response(minimal_config)
    # HAConfigPublic has no token field at all.
    assert not hasattr(resp.ha, "token")
    assert resp.ha.url == minimal_config.ha.url
    assert resp.auth.password_set is False  # minimal_config has empty password
    assert "zone_a" in resp.zones
    assert resp.restart_required is False


def test_response_password_set_true_when_configured(minimal_config: AppConfig) -> None:
    data = minimal_config.model_dump()
    data["auth"]["password"] = "$2b$12$hash"
    cfg = AppConfig.model_validate(data)
    assert build_config_response(cfg).auth.password_set is True


# ── build_validated_config (secret carry-through + validation) ────────────────


def test_update_carries_secrets_from_current(minimal_config: AppConfig) -> None:
    body = build_config_response(minimal_config).model_dump()  # no secrets in it
    fresh = build_validated_config(body, minimal_config)
    assert fresh.ha.token == minimal_config.ha.token  # carried through, not from client
    assert fresh.auth.password == minimal_config.auth.password


def test_update_ignores_client_supplied_secret(minimal_config: AppConfig) -> None:
    body = build_config_response(minimal_config).model_dump()
    body["ha"]["token"] = "attacker-supplied"  # must be overridden by the server
    fresh = build_validated_config(body, minimal_config)
    assert fresh.ha.token == minimal_config.ha.token


def test_update_rejects_unknown_zone_reference(minimal_config: AppConfig) -> None:
    body = build_config_response(minimal_config).model_dump()
    body["sequences"]["seq_1"]["zones"] = ["ghost_zone"]
    with pytest.raises(ValidationError, match="ghost_zone"):
        build_validated_config(body, minimal_config)


def test_update_accepts_added_zone_and_sequence(minimal_config: AppConfig) -> None:
    body = build_config_response(minimal_config).model_dump()
    body["zones"]["zone_c"] = {"label": "Zone C", "switch": "switch.zone_c", "flow_lph": 100.0}
    body["sequences"]["seq_1"]["zones"] = ["zone_a", "zone_c"]
    fresh = build_validated_config(body, minimal_config)
    assert "zone_c" in fresh.zones
    assert fresh.sequences["seq_1"].zones == ["zone_a", "zone_c"]


def test_update_rejects_password_mode_without_password(minimal_config: AppConfig) -> None:
    # minimal_config has no password; enabling password auth would lock everyone out.
    body = build_config_response(minimal_config).model_dump()
    body["auth"]["mode"] = "password"
    with pytest.raises(ValueError, match="requires a password"):
        build_validated_config(body, minimal_config)


def test_update_allows_password_mode_when_password_already_set(minimal_config: AppConfig) -> None:
    data = minimal_config.model_dump()
    data["auth"]["password"] = "$2b$12$hash"
    current = AppConfig.model_validate(data)  # password is environment-managed → already present
    body = build_config_response(current).model_dump()
    body["auth"]["mode"] = "password"
    fresh = build_validated_config(body, current)
    assert fresh.auth.mode == "password"
    assert fresh.auth.password == "$2b$12$hash"  # carried through from current


# ── export ────────────────────────────────────────────────────────────────────


def test_export_dict_strips_secrets(minimal_config: AppConfig) -> None:
    data = minimal_config.model_dump()
    data["ha"]["token"] = "live"
    data["auth"]["password"] = "pw"
    cfg = AppConfig.model_validate(data)
    exported = to_export_dict(cfg)
    assert exported["ha"]["token"] == ""
    assert exported["auth"]["password"] == ""


# ── HAClient.list_entities (entity picker source) ─────────────────────────────


def test_list_entities_filters_by_domain_and_sorts() -> None:
    ha = HAClient(url="ws://x", token="t")
    ha._state_cache = {
        "switch.b": {"state": "off", "attributes": {"friendly_name": "B"}},
        "switch.a": {"state": "on", "attributes": {"friendly_name": "A"}},
        "sensor.temp": {"state": "21.0", "attributes": {}},
    }

    switches = ha.list_entities("switch")
    assert [e["entity_id"] for e in switches] == ["switch.a", "switch.b"]
    assert switches[0]["friendly_name"] == "A"
    assert switches[0]["domain"] == "switch"

    sensors = ha.list_entities("sensor")
    assert [e["entity_id"] for e in sensors] == ["sensor.temp"]
    assert sensors[0]["friendly_name"] is None

    assert len(ha.list_entities()) == 3  # no filter → all
