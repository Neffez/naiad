"""Full-document configuration API (Phase 6a).

The database is the source of truth for the configuration; these endpoints read
and replace it as a single validated document and apply changes to the running
system without a restart. Secrets (ha.token, auth.password) are never exposed and
never accepted from clients — they stay environment-managed and are carried
through from the running configuration on every update.
"""

import logging
from collections.abc import Callable
from typing import Any

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlmodel import Session

from naiad.api.schemas import (
    AuthConfigResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    EntitiesResponse,
    EntityInfo,
    HAConfigPublic,
)
from naiad.config import AppConfig
from naiad.config_store import save_config_doc, to_export_dict
from naiad.dependencies import (
    get_config,
    get_ha_client,
    get_runner,
    get_scheduler,
    get_session_factory,
    get_tracker,
    require_auth,
)
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.ha_client import HAClient
from naiad.runtime_reload import apply_reloaded_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# ── Pure helpers (unit-tested directly) ───────────────────────────────────────


def build_config_response(config: AppConfig, *, restart_required: bool = False) -> ConfigResponse:
    """Project an AppConfig to the public response, redacting secrets."""
    return ConfigResponse(
        ha=HAConfigPublic(url=config.ha.url, notify_targets=config.ha.notify_targets),
        auth=AuthConfigResponse(
            mode=config.auth.mode,
            forward_header=config.auth.forward_header,
            auto_login=config.auth.auto_login,
            frame_ancestors=config.auth.frame_ancestors,
            password_set=bool(config.auth.password),
        ),
        sensors=config.sensors,
        zones=config.zones,
        sequences=config.sequences,
        factors=config.factors,
        timezone=config.timezone,
        restart_required=restart_required,
    )


def build_validated_config(data: dict[str, Any], current: AppConfig) -> AppConfig:
    """Validate an incoming config dict, carrying secrets through from ``current``.

    Raises pydantic ValidationError on invalid input (shape or cross-field rules
    such as unknown zone references / range / timezone).
    """
    data = dict(data)
    # Tolerate a naive GET→edit→PUT round-trip: drop response-only fields that
    # AppConfig (extra="forbid") would otherwise reject.
    data.pop("restart_required", None)
    data["ha"] = {**data.get("ha", {}), "token": current.ha.token}
    auth = {**data.get("auth", {}), "password": current.auth.password}
    auth.pop("password_set", None)
    data["auth"] = auth
    return AppConfig.model_validate(data)


def _persist_and_reload(
    fresh: AppConfig,
    *,
    current: AppConfig,
    scheduler: AsyncIOScheduler,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: Callable[[], Session],
    tracker: LiterTracker,
) -> bool:
    """Persist a validated config and apply it live. Returns restart_required."""
    restart_required = fresh.ha.url != current.ha.url or fresh.ha.token != current.ha.token
    with session_factory() as session:
        save_config_doc(session, fresh)
    apply_reloaded_config(
        current,
        fresh,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
    )
    return restart_required


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=ConfigResponse)
async def get_configuration(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
) -> ConfigResponse:
    return build_config_response(config)


@router.put("", response_model=ConfigResponse)
async def replace_configuration(
    body: ConfigUpdateRequest,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
    ha: HAClient = Depends(get_ha_client),
    tracker: LiterTracker = Depends(get_tracker),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> ConfigResponse:
    if runner.status().sequence_id is not None:
        raise HTTPException(409, "Cannot change configuration while a sequence is running")
    try:
        fresh = build_validated_config(body.model_dump(), config)
    except ValidationError as e:
        raise HTTPException(422, f"Invalid configuration: {e}") from e

    restart_required = _persist_and_reload(
        fresh,
        current=config,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
    )
    return build_config_response(config, restart_required=restart_required)


@router.get("/export")
async def export_configuration(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
) -> Response:
    text = yaml.safe_dump(to_export_dict(config), sort_keys=False, allow_unicode=True)
    return Response(
        content=text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="naiad-config.yaml"'},
    )


@router.post("/import", response_model=ConfigResponse)
async def import_configuration(
    request: Request,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
    ha: HAClient = Depends(get_ha_client),
    tracker: LiterTracker = Depends(get_tracker),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> ConfigResponse:
    if runner.status().sequence_id is not None:
        raise HTTPException(409, "Cannot change configuration while a sequence is running")
    raw = await request.body()
    try:
        data = yaml.safe_load(raw)  # YAML is a JSON superset
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Could not parse uploaded config: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(400, "Uploaded config must be a YAML/JSON object")
    try:
        fresh = build_validated_config(data, config)
    except ValidationError as e:
        raise HTTPException(422, f"Invalid configuration: {e}") from e

    restart_required = _persist_and_reload(
        fresh,
        current=config,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
    )
    return build_config_response(config, restart_required=restart_required)


@router.get("/entities", response_model=EntitiesResponse)
async def list_entities(
    domain: str | None = None,
    _: None = Depends(require_auth),
    ha: HAClient = Depends(get_ha_client),
) -> EntitiesResponse:
    """List cached HA entities for the UI entity picker (optionally by domain)."""
    return EntitiesResponse(entities=[EntityInfo(**e) for e in ha.list_entities(domain)])
