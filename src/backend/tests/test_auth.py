from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from naiad.api.auth import _auto_login_enabled, _check_password, _match_by_prefix
from naiad.config import AppConfig
from naiad.domain.models import AuthToken, UserPreference


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
