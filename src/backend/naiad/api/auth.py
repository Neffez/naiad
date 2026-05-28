import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from naiad.api.schemas import AuthTokenResponse, AutoLoginRequest, LoginRequest, LoginResponse
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import AuthToken

router = APIRouter(prefix="/auth", tags=["auth"])

_DEFAULT_TOKEN_LIFETIME_DAYS = 30


def _token_lifetime(session: Session) -> int:
    from naiad.domain.models import UserPreference
    pref = session.get(UserPreference, "token_lifetime_days")
    if pref is not None:
        try:
            return int(pref.value)
        except ValueError:
            pass
    return _DEFAULT_TOKEN_LIFETIME_DAYS


def _check_password(provided: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        return bcrypt.checkpw(provided.encode(), stored.encode())
    return provided == stored


def _issue_token(body_label: str | None, session: Session, config: AppConfig) -> LoginResponse:
    lifetime = _token_lifetime(session)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=lifetime)
    session.add(AuthToken(
        token=token,
        device_label=body_label,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    ))
    session.commit()
    return LoginResponse(token=token, expires_at=expires_at)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> LoginResponse:
    if config.auth.mode != "password":
        raise HTTPException(422, "Password auth is not enabled")
    if not config.auth.password:
        raise HTTPException(503, "Server password not configured")
    if not _check_password(body.password, config.auth.password):
        raise HTTPException(401, "Invalid password")
    return _issue_token(body.device_label, session, config)


@router.post("/auto-login", response_model=LoginResponse)
async def auto_login(
    body: AutoLoginRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> LoginResponse:
    al = config.auth.auto_login
    if not al.enabled:
        raise HTTPException(403, "Auto-login not enabled")
    if not body.embed_param_present:
        raise HTTPException(403, "embed param not present")

    referer = request.headers.get("referer", "")
    client_ip = request.client.host if request.client else ""

    referer_ok = not al.trigger.trusted_referers or any(
        r in referer for r in al.trigger.trusted_referers
    )
    ip_ok = not al.trigger.trusted_ips or client_ip in al.trigger.trusted_ips

    if not (referer_ok and ip_ok):
        raise HTTPException(403, "Auto-login conditions not met")

    return _issue_token(body.device_label, session, config)


@router.get("/verify")
async def verify(_: None = Depends(require_auth)) -> dict:
    return {"ok": True}


@router.get("/tokens", response_model=list[AuthTokenResponse])
async def list_tokens(
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> list[AuthTokenResponse]:
    tokens = session.exec(select(AuthToken)).all()
    return [
        AuthTokenResponse(
            token_prefix=t.token[:8],
            device_label=t.device_label,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
            expires_at=t.expires_at,
        )
        for t in tokens
    ]


@router.delete("/tokens/{token_prefix}", status_code=204)
async def revoke_token(
    token_prefix: str,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> None:
    tokens = session.exec(select(AuthToken)).all()
    match = next((t for t in tokens if t.token.startswith(token_prefix)), None)
    if match is None:
        raise HTTPException(404, "Token not found")
    session.delete(match)
    session.commit()
