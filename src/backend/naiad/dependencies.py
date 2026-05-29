from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from naiad.auth_rules import INGRESS_HEADER, forward_header_ok, ingress_request_ok
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.domain.models import AuthToken
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.ha_client import HAClient

_bearer = HTTPBearer(auto_error=False)


def get_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client  # type: ignore[no-any-return]


def get_runner(request: Request) -> SequenceRunner:
    return request.app.state.runner  # type: ignore[no-any-return]


def get_scheduler(request: Request) -> AsyncIOScheduler:
    return request.app.state.scheduler


def get_tracker(request: Request) -> LiterTracker:
    return request.app.state.tracker  # type: ignore[no-any-return]


def get_session_factory(request: Request) -> Callable[[], Session]:
    return request.app.state.session_factory  # type: ignore[no-any-return]


async def require_auth(
    request: Request,
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    client_ip = request.client.host if request.client else ""

    # Ingress trust applies on top of any mode: a request proxied by the Supervisor
    # ingress is already authenticated by Home Assistant. The configured mode still
    # governs the direct port, which does not pass through HA auth.
    if ingress_request_ok(client_ip, request.headers.get(INGRESS_HEADER, ""), config.auth.ingress):
        return

    if config.auth.mode == "none":
        return

    if config.auth.mode == "forward_header":
        header_value = request.headers.get(config.auth.forward_header.header, "")
        if forward_header_ok(header_value, client_ip, config.auth.forward_header):
            return
        raise HTTPException(status_code=401, detail="Forward-auth header missing or untrusted")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token_str = credentials.credentials
    db_token = session.get(AuthToken, token_str)

    if db_token is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    if db_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Token expired")

    db_token.last_used_at = datetime.now(UTC)
    session.add(db_token)
    session.commit()
