from fastapi import Request

from naiad.config import AppConfig
from naiad.ha_client import HAClient


def get_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client  # type: ignore[no-any-return]
