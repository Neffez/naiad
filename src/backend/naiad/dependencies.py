from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from naiad.config import AppConfig
from naiad.database import get_session
from naiad.domain.models import AuthToken
from naiad.domain.sequences import SequenceRunner
from naiad.ha_client import HAClient

_bearer = HTTPBearer(auto_error=False)


def get_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client  # type: ignore[no-any-return]


def get_runner(request: Request) -> SequenceRunner:
    return request.app.state.runner  # type: ignore[no-any-return]


def get_scheduler(request: Request) -> AsyncIOScheduler:
    return request.app.state.scheduler  # type: ignore[no-any-return]


async def require_auth(
    config: AppConfig = Depends(get_config),
    session: Session = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if config.auth.mode == "none":
        return

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
