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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlmodel import Session

from naiad.api.schemas import (
    AuthConfigResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    EntitiesResponse,
    EntityInfo,
    HAConfigPublic,
    MQTTConfigResponse,
    ServicesResponse,
)
from naiad.config import AppConfig, target_service_data
from naiad.config_store import save_config_doc, to_export_dict
from naiad.dependencies import (
    get_config,
    get_ha_client,
    get_runner,
    get_scheduler,
    get_session_factory,
    get_stats_publisher,
    get_tracker,
    require_auth,
)
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.ha_client import HAClient, HAError
from naiad.i18n import t
from naiad.runtime_reload import apply_reloaded_config
from naiad.stats_publisher import StatsPublisher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# ── Pure helpers (unit-tested directly) ───────────────────────────────────────


def build_config_response(config: AppConfig, *, restart_required: bool = False) -> ConfigResponse:
    """Project an AppConfig to the public response, redacting secrets."""
    return ConfigResponse(
        ha=HAConfigPublic(url=config.ha.url, notify_targets=config.ha.notify_targets),
        mqtt=MQTTConfigResponse(
            enabled=config.mqtt.enabled,
            host=config.mqtt.host,
            port=config.mqtt.port,
            username=config.mqtt.username,
            client_id=config.mqtt.client_id,
            discovery_prefix=config.mqtt.discovery_prefix,
            base_topic=config.mqtt.base_topic,
            password_set=bool(config.mqtt.password),
        ),
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
        notifications=config.notifications,
        timezone=config.timezone,
        sequence_colors_enabled=config.sequence_colors_enabled,
        restart_required=restart_required,
    )


def build_validated_config(data: dict[str, Any], current: AppConfig) -> AppConfig:
    """Validate an incoming config dict, carrying secrets through from ``current``.

    Raises pydantic ValidationError on invalid input (shape or cross-field rules
    such as unknown zone references / range / timezone), and ValueError when the
    request would lock everyone out (see the password guard below).
    """
    data = dict(data)
    # Tolerate a naive GET→edit→PUT round-trip: drop response-only fields that
    # AppConfig (extra="forbid") would otherwise reject.
    data.pop("restart_required", None)
    data["ha"] = {**data.get("ha", {}), "token": current.ha.token}
    auth = {**data.get("auth", {}), "password": current.auth.password}
    auth.pop("password_set", None)
    data["auth"] = auth
    # The MQTT password is environment-managed too: carry it through and never
    # accept it from a client (drop the response-only password_set flag).
    mqtt = {**data.get("mqtt", {}), "password": current.mqtt.password}
    mqtt.pop("password_set", None)
    data["mqtt"] = mqtt
    config = AppConfig.model_validate(data)

    # Lockout guard: password auth requires a password, but the password is
    # environment-managed and never accepted from clients. Switching to
    # mode=password without one configured would make /auth/login return 503 and
    # require_auth reject every request — locking the user out of the UI (and the
    # very endpoint needed to undo it). Reject it up front instead.
    if config.auth.mode == "password" and not config.auth.password:
        raise ValueError(
            "auth.mode='password' requires a password, but none is configured. "
            "Set NAIAD_PASSWORD_HASH in the environment before enabling password auth."
        )
    return config


def _persist_and_reload(
    fresh: AppConfig,
    *,
    current: AppConfig,
    scheduler: AsyncIOScheduler,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: Callable[[], Session],
    tracker: LiterTracker,
    stats_publisher: StatsPublisher,
) -> bool:
    """Persist a validated config and apply it live. Returns restart_required."""
    # The token is environment-managed and carried through unchanged, so only a
    # URL change can require a reconnect (the live HA socket is not re-dialed).
    restart_required = fresh.ha.url != current.ha.url
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
        stats_publisher=stats_publisher,
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
    stats_publisher: StatsPublisher = Depends(get_stats_publisher),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> ConfigResponse:
    # The path from this guard to the in-place mutation in _persist_and_reload is
    # deliberately ``await``-free: on the single-threaded event loop no scheduler
    # job or other request can interleave between the check and the swap, so the
    # reload is atomic against a run starting or a valve operation entering its
    # protected section. Keep it synchronous.
    if not runner.can_reload_config():
        raise HTTPException(409, "Cannot change configuration while valve operations are active")
    try:
        fresh = build_validated_config(body.model_dump(), config)
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, f"Invalid configuration: {e}") from e

    restart_required = _persist_and_reload(
        fresh,
        current=config,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
        stats_publisher=stats_publisher,
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
    stats_publisher: StatsPublisher = Depends(get_stats_publisher),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
) -> ConfigResponse:
    if not runner.can_reload_config():
        raise HTTPException(409, "Cannot change configuration while valve operations are active")
    raw = await request.body()
    try:
        data = yaml.safe_load(raw)  # YAML is a JSON superset
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Could not parse uploaded config: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(400, "Uploaded config must be a YAML/JSON object")
    try:
        fresh = build_validated_config(data, config)
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, f"Invalid configuration: {e}") from e

    # ``await request.body()`` above is a yield point, so a run could have started
    # since the first guard. Re-check right before the (synchronous) swap so the
    # reload can never race a just-started run or protected valve operation.
    if not runner.can_reload_config():
        raise HTTPException(409, "Cannot change configuration while valve operations are active")

    restart_required = _persist_and_reload(
        fresh,
        current=config,
        scheduler=scheduler,
        runner=runner,
        ha=ha,
        session_factory=session_factory,
        tracker=tracker,
        stats_publisher=stats_publisher,
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


@router.get("/services", response_model=ServicesResponse)
async def list_services(
    domain: str | None = None,
    _: None = Depends(require_auth),
    ha: HAClient = Depends(get_ha_client),
) -> ServicesResponse:
    """List HA services (e.g. notify.*) for the picker. Services aren't entities, so
    this queries HA directly; returns empty if HA is unreachable."""
    try:
        services = await ha.get_services(domain)
    except HAError:
        services = []
    return ServicesResponse(services=services)


@router.post("/test-notify")
async def test_notify(
    service: str | None = Query(default=None),
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    ha: HAClient = Depends(get_ha_client),
) -> dict[str, object]:
    """Send a test push to configured notify targets.

    If *service* is given, only that target is tested; otherwise all targets are
    tested. Reports exactly what failed."""
    targets = config.ha.notify_targets
    if service is not None:
        targets = [t for t in targets if t.service == service]
        if not targets:
            raise HTTPException(404, f"Notify target '{service}' not found in configuration.")
    elif not targets:
        raise HTTPException(
            400, "No notify targets configured. Add at least one (notify.*) in the configuration."
        )
    message = t("test.notification", config.language)
    failures: list[str] = []
    for target in targets:
        try:
            await ha.call_service(
                "notify",
                target.service.removeprefix("notify."),
                **target_service_data(target, message),
            )
        except Exception as e:  # noqa: BLE001 — surface the reason to the user
            failures.append(f"{target.service}: {e}")
    if failures:
        raise HTTPException(502, "Notification failed — " + "; ".join(failures))
    return {"sent": len(targets), "targets": [t.service for t in targets]}
