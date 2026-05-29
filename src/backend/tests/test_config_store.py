import json

import pytest
import yaml
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.config import AppConfig
from naiad.config_store import (
    build_bootstrap_config,
    load_config_doc,
    load_or_seed_config,
    save_config_doc,
)
from naiad.domain.models import ConfigDocument
from tests.conftest import MINIMAL_CONFIG_DATA


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return lambda: Session(engine)


def test_load_returns_none_when_empty(session_factory) -> None:
    with session_factory() as session:
        assert load_config_doc(session) is None


def test_save_then_load_roundtrip(session_factory, minimal_config: AppConfig, monkeypatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "secret-token")
    with session_factory() as session:
        save_config_doc(session, minimal_config)
    with session_factory() as session:
        loaded = load_config_doc(session)

    assert loaded is not None
    assert loaded.ha.url == minimal_config.ha.url
    assert set(loaded.zones) == set(minimal_config.zones)
    assert loaded.sequences["seq_wind"].wind_blocks is True
    assert loaded.factors.temp.basis_c == minimal_config.factors.temp.basis_c


def test_secrets_are_not_persisted(session_factory, minimal_config: AppConfig) -> None:
    """ha.token / auth.password must never be written to the database."""
    assert minimal_config.ha.token == "test_token"  # present in the in-memory config
    with session_factory() as session:
        save_config_doc(session, minimal_config)
        row = session.get(ConfigDocument, 1)

    assert row is not None
    stored = json.loads(row.data)
    assert stored["ha"]["token"] == ""
    assert stored["auth"]["password"] == ""
    assert "test_token" not in row.data


def test_secret_reinjected_from_env_on_load(
    session_factory, minimal_config: AppConfig, monkeypatch
) -> None:
    with session_factory() as session:
        save_config_doc(session, minimal_config)

    monkeypatch.setenv("HA_TOKEN", "live-token")
    monkeypatch.setenv("NAIAD_PASSWORD_HASH", "$2b$12$hash")
    with session_factory() as session:
        loaded = load_config_doc(session)

    assert loaded is not None
    assert loaded.ha.token == "live-token"
    assert loaded.auth.password == "$2b$12$hash"


def test_save_is_idempotent_singleton(session_factory, minimal_config: AppConfig) -> None:
    with session_factory() as session:
        save_config_doc(session, minimal_config)
        save_config_doc(session, minimal_config)
    with session_factory() as session:
        rows = list(session.exec(select(ConfigDocument)).all())
    assert len(rows) == 1


def test_load_or_seed_seeds_from_yaml_then_prefers_db(
    session_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HA_TOKEN", "yaml-token")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(MINIMAL_CONFIG_DATA), encoding="utf-8")

    # First call: no DB document yet → seed from YAML.
    seeded = load_or_seed_config(session_factory, yaml_path)
    assert "zone_a" in seeded.zones
    with session_factory() as session:
        assert session.get(ConfigDocument, 1) is not None

    # YAML disappears, but the DB is now authoritative.
    yaml_path.unlink()
    reloaded = load_or_seed_config(session_factory, yaml_path)
    assert set(reloaded.zones) == set(seeded.zones)


def test_load_or_seed_bootstraps_empty_by_default(session_factory, tmp_path, monkeypatch) -> None:
    """No DB document and no YAML → start empty, not an error (config.yaml is optional)."""
    monkeypatch.setenv("HA_TOKEN", "boot-token")
    config = load_or_seed_config(session_factory, tmp_path / "missing.yaml")

    assert config.zones == {}
    assert config.sequences == {}
    assert config.sensors.rain == ""
    assert config.ha.token == "boot-token"
    assert config.auth.mode == "none"  # UI reachable without a password on first boot
    # Persisted, so the next boot loads it from the DB.
    with session_factory() as session:
        assert load_config_doc(session) is not None


# ── Bootstrap auth per deployment (Phase 6d) ──────────────────────────────────


def test_bootstrap_auth_standalone_is_open(monkeypatch) -> None:
    """Standalone, no password env → mode 'none' so the zero-config UI is reachable."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("NAIAD_PASSWORD_HASH", raising=False)
    config = build_bootstrap_config()
    assert config.auth.mode == "none"
    assert config.auth.ingress.enabled is True


def test_bootstrap_auth_addon_uses_password_with_ingress(monkeypatch) -> None:
    """Add-on context, no password → 'password' mode (sidebar via ingress trust)."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    monkeypatch.delenv("NAIAD_PASSWORD_HASH", raising=False)
    config = build_bootstrap_config()
    assert config.auth.mode == "password"
    assert config.auth.password == ""
    assert config.auth.ingress.enabled is True


def test_bootstrap_auth_seeds_password_from_env(monkeypatch) -> None:
    """A seeded password locks the direct port from the first boot, in any context."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setenv("NAIAD_PASSWORD_HASH", "$2b$12$abcdefghijklmnopqrstuv")
    config = build_bootstrap_config()
    assert config.auth.mode == "password"
    assert config.auth.password == "$2b$12$abcdefghijklmnopqrstuv"
