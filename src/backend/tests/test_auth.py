import asyncio
import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from naiad.api.auth import _auto_login_enabled, _check_password, _match_by_prefix
from naiad.config import AppConfig
from naiad.dependencies import require_auth
from naiad.domain.models import AuthToken, UserPreference
from tests.conftest import MINIMAL_CONFIG_DATA


def _token(value: str) -> AuthToken:
    return AuthToken(
        token=value,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def test_match_by_prefix_unique() -> None:
    tokens = [_token("aaaaaaaa1111"), _token("bbbbbbbb2222")]
    match = _match_by_prefix(tokens, "aaaaaaaa")
    assert match.token == "aaaaaaaa1111"


def test_match_by_prefix_not_found() -> None:
    tokens = [_token("aaaaaaaa1111")]
    with pytest.raises(HTTPException) as exc:
        _match_by_prefix(tokens, "zzzzzzzz")
    assert exc.value.status_code == 404


def test_match_by_prefix_ambiguous_rejected() -> None:
    """Two tokens sharing an 8-char prefix must not silently revoke one."""
    tokens = [_token("aaaaaaaa1111"), _token("aaaaaaaa2222")]
    with pytest.raises(HTTPException) as exc:
        _match_by_prefix(tokens, "aaaaaaaa")
    assert exc.value.status_code == 409


def test_match_by_prefix_requires_full_prefix() -> None:
    """A partial prefix is no longer accepted (exact 8-char equality)."""
    tokens = [_token("aaaaaaaa1111")]
    with pytest.raises(HTTPException) as exc:
        _match_by_prefix(tokens, "aaaa")
    assert exc.value.status_code == 404


def _mem_session() -> Session:
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def test_auto_login_enabled_db_pref_overrides_yaml(minimal_config: AppConfig) -> None:
    """The Settings toggle (DB pref) must take effect over the YAML default."""
    # YAML default is disabled.
    assert minimal_config.auth.auto_login.enabled is False

    with _mem_session() as session:
        # No pref → falls back to YAML (disabled).
        assert _auto_login_enabled(minimal_config, session) is False

        # Pref enables it.
        session.add(UserPreference(key="auto_login_enabled", value="1"))
        session.commit()
        assert _auto_login_enabled(minimal_config, session) is True

        # Pref disables it.
        pref = session.get(UserPreference, "auto_login_enabled")
        assert pref is not None
        pref.value = "0"
        session.add(pref)
        session.commit()
        assert _auto_login_enabled(minimal_config, session) is False


def test_check_password_bcrypt_and_plain() -> None:
    import bcrypt

    hashed = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    assert _check_password("secret", hashed) is True
    assert _check_password("wrong", hashed) is False
    assert _check_password("plain", "plain") is True
    assert _check_password("plain", "") is False


# ── require_auth ingress trust (Phase 6d) ─────────────────────────────────────


def _password_config() -> AppConfig:
    data = copy.deepcopy(MINIMAL_CONFIG_DATA)
    data["auth"] = {"mode": "password", "password": ""}  # locked-out without ingress
    return AppConfig.model_validate(data)


def _fake_request(client_ip: str, headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=client_ip), headers=headers)


def test_require_auth_passes_for_ingress_request() -> None:
    """A Supervisor-proxied request is accepted in password mode without a token."""
    config = _password_config()
    request = _fake_request("172.30.32.2", {"X-Ingress-Path": "/api/hassio_ingress/tok"})
    with _mem_session() as session:
        # Should not raise despite mode=password and no credentials.
        assert asyncio.run(require_auth(request, config, session, None)) is None


def test_require_auth_rejects_direct_request_without_token() -> None:
    """The direct port (no ingress headers, real client IP) still needs a token."""
    config = _password_config()
    request = _fake_request("192.168.1.50", {})
    with _mem_session() as session, pytest.raises(HTTPException) as exc:
        asyncio.run(require_auth(request, config, session, None))
    assert exc.value.status_code == 401
