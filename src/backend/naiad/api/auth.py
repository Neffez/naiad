import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from naiad.api.schemas import AuthTokenResponse, AutoLoginRequest, LoginRequest, LoginResponse
from naiad.auth_rules import referer_matches
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, require_auth
from naiad.domain.models import AuthToken, UserPreference

router = APIRouter(prefix="/auth", tags=["auth"])

_DEFAULT_TOKEN_LIFETIME_DAYS = 30


# ── Login throttling ──────────────────────────────────────────────────────────


@dataclass
class _IPAttempts:
    failures: int = 0
    locked_until: float = 0.0
    last_seen: float = 0.0


class LoginThrottle:
    """In-memory per-IP throttle for the shared-password login.

    The single shared password is brute-forceable, so after a few wrong guesses
    from one source IP we impose a growing temporary lockout. State is per-IP and
    in-memory only (a process restart clears it, which is acceptable). A correct
    password clears that IP's counter. Pure and clock-injectable for testing.
    """

    def __init__(
        self,
        *,
        free_attempts: int = 5,
        base_lockout_s: float = 60.0,
        max_lockout_s: float = 900.0,
        reset_after_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._free = free_attempts
        self._base = base_lockout_s
        self._max = max_lockout_s
        self._reset_after = reset_after_s
        self._clock = clock
        self._state: dict[str, _IPAttempts] = {}

    def _prune(self, now: float) -> None:
        # Drop entries that are not locked and have been idle past the reset
        # window, so the table can't grow unbounded.
        stale = [
            ip
            for ip, s in self._state.items()
            if s.locked_until <= now and now - s.last_seen > self._reset_after
        ]
        for ip in stale:
            del self._state[ip]

    def retry_after(self, ip: str) -> float:
        """Seconds until ``ip`` may try again (0 if not currently locked)."""
        if not ip:
            return 0.0
        s = self._state.get(ip)
        if s is None:
            return 0.0
        return max(0.0, s.locked_until - self._clock())

    def record_failure(self, ip: str) -> None:
        if not ip:
            return
        now = self._clock()
        s = self._state.setdefault(ip, _IPAttempts())
        if now - s.last_seen > self._reset_after:
            s.failures = 0  # stale history — start fresh
        s.last_seen = now
        s.failures += 1
        if s.failures > self._free:
            # 1st lockout = base, then double each further failure, capped.
            steps = s.failures - self._free - 1
            s.locked_until = now + min(self._max, self._base * (2**steps))
        self._prune(now)

    def record_success(self, ip: str) -> None:
        self._state.pop(ip, None)


# Module-level singleton used by the login route; tests can reset it via the
# fixture in tests/test_auth.py.
_login_throttle = LoginThrottle()


def _token_lifetime(session: Session) -> int:
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
    # Plaintext fallback — constant-time to avoid a timing oracle. Compared as
    # bytes: compare_digest raises TypeError for non-ASCII str inputs.
    return secrets.compare_digest(provided.encode(), stored.encode())


def _issue_token(body_label: str | None, session: Session) -> LoginResponse:
    lifetime = _token_lifetime(session)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=lifetime)
    session.add(
        AuthToken(
            token=token,
            device_label=body_label,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
    )
    session.commit()
    return LoginResponse(token=token, expires_at=expires_at)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> LoginResponse:
    if config.auth.mode != "password":
        raise HTTPException(422, "Password auth is not enabled")
    if not config.auth.password:
        raise HTTPException(503, "Server password not configured")

    client_ip = request.client.host if request.client else ""
    retry_after = _login_throttle.retry_after(client_ip)
    if retry_after > 0:
        raise HTTPException(
            429,
            "Too many failed login attempts — try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    if not _check_password(body.password, config.auth.password):
        _login_throttle.record_failure(client_ip)
        raise HTTPException(401, "Invalid password")

    _login_throttle.record_success(client_ip)
    return _issue_token(body.device_label, session)


def _auto_login_enabled(config: AppConfig, session: Session) -> bool:
    """Effective auto-login flag: the Settings toggle (DB) overrides the YAML default."""
    pref = session.get(UserPreference, "auto_login_enabled")
    if pref is not None:
        return pref.value == "1"
    return config.auth.auto_login.enabled


@router.post("/auto-login", response_model=LoginResponse)
async def auto_login(
    body: AutoLoginRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
) -> LoginResponse:
    al = config.auth.auto_login
    if not _auto_login_enabled(config, session):
        raise HTTPException(403, "Auto-login not enabled")
    if not body.embed_param_present:
        raise HTTPException(403, "embed param not present")

    # Refuse to hand out a token to anyone: at least one trust condition must be
    # configured, and every configured condition must hold.
    if not (al.trigger.trusted_referers or al.trigger.trusted_ips):
        raise HTTPException(403, "Auto-login requires trusted_referers or trusted_ips")

    referer = request.headers.get("referer", "")
    client_ip = request.client.host if request.client else ""

    referer_ok = not al.trigger.trusted_referers or referer_matches(
        referer, al.trigger.trusted_referers
    )
    ip_ok = not al.trigger.trusted_ips or client_ip in al.trigger.trusted_ips

    if not (referer_ok and ip_ok):
        raise HTTPException(403, "Auto-login conditions not met")

    return _issue_token(body.device_label, session)


@router.get("/verify")
async def verify(_: None = Depends(require_auth)) -> dict[str, bool]:
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


def _match_by_prefix(tokens: list[AuthToken], token_prefix: str) -> AuthToken:
    """Find the single token whose 8-char prefix equals token_prefix.

    Uses exact prefix equality (not startswith) and rejects ambiguous matches,
    so a short/partial prefix can never silently revoke the wrong token.
    """
    matches = [t for t in tokens if t.token[:8] == token_prefix]
    if not matches:
        raise HTTPException(404, "Token not found")
    if len(matches) > 1:
        raise HTTPException(409, "Token prefix is ambiguous")
    return matches[0]


@router.delete("/tokens/{token_prefix}", status_code=204)
async def revoke_token(
    token_prefix: str,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> None:
    tokens = list(session.exec(select(AuthToken)).all())
    match = _match_by_prefix(tokens, token_prefix)
    session.delete(match)
    session.commit()
