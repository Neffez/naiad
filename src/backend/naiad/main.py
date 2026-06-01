import json
import logging
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Scope

from naiad import __version__
from naiad.config import is_addon_context, resolve_ha_connection
from naiad.config_store import load_or_seed_config
from naiad.database import create_tables, get_engine
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.drivers.ha_driver import HAEntityDriver
from naiad.ha_client import HAClient
from naiad.scheduler import refresh_fallback_temp_max, setup_scheduler
from naiad.stats_publisher import StatsPublisher

# ── Logging ───────────────────────────────────────────────────────────────────


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        skip = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "message",
            "taskName",
        }
        for key, val in record.__dict__.items():
            if key not in skip:
                obj[key] = val
        return json.dumps(obj, default=str)


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # APScheduler logs an INFO line per job execution (the plan tick runs every
    # minute), which floods the log — keep only its warnings/errors.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ── Request-ID middleware ─────────────────────────────────────────────────────


class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        req_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# ── Security-headers middleware ───────────────────────────────────────────────


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Emit Content-Security-Policy: frame-ancestors from auth.frame_ancestors,
    so the configured HA-dashboard-embedding policy is actually enforced."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        config = getattr(request.app.state, "config", None)
        if config is not None:
            ancestors = " ".join(config.auth.frame_ancestors) or "'none'"
            response.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
        return response


# ── Lifespan ──────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _setup_logging()
    logger.info("Naiad starting")

    create_tables()
    logger.info("Database tables ready")

    def _session_factory() -> Session:
        return Session(get_engine())

    # Database is the source of truth; config.yaml seeds it on first boot only.
    config = load_or_seed_config(_session_factory)
    logger.info(
        "Config loaded", extra={"zones": len(config.zones), "sequences": len(config.sequences)}
    )
    if config.auth.mode == "none":
        logger.warning(
            "Authentication is DISABLED (auth.mode='none'): the API is open to anyone who "
            "can reach it. This is only safe behind Home Assistant ingress or a trusted "
            "reverse proxy. Configure password or forward_header auth before exposing Naiad."
        )
    if config.auth.mode == "forward_header" and not config.auth.forward_header.trusted_proxies:
        logger.warning(
            "auth.mode='forward_header' with no auth.forward_header.trusted_proxies: the "
            "'%s' header is trusted from ANY client, so anyone who can reach the direct port "
            "can impersonate any user. Set trusted_proxies to your reverse-proxy IP(s).",
            config.auth.forward_header.header,
        )

    # In the HA add-on context, reach Core through the Supervisor proxy with the
    # auto-provided SUPERVISOR_TOKEN; standalone uses the configured URL/token.
    ha_url, ha_token = resolve_ha_connection(config.ha.url, config.ha.token)
    ha = HAClient(url=ha_url, token=ha_token)

    driver = HAEntityDriver(ha)
    runner = SequenceRunner(config, driver, _session_factory)
    _tracker = LiterTracker(ha, config, _session_factory, runner.is_managed)

    # Mirror tracked liters/durations into Home Assistant over MQTT (best-effort,
    # disabled unless configured). Runner and tracker both write run history, so
    # both refresh the published totals once a run is recorded.
    stats_publisher = StatsPublisher(config, _session_factory)
    runner.on_run_recorded = stats_publisher.on_run_recorded
    _tracker.on_run_recorded = stats_publisher.on_run_recorded

    scheduler = setup_scheduler(config, runner, ha, _session_factory)
    scheduler.start()
    logger.info("Scheduler started (%d jobs)", len(scheduler.get_jobs()))

    from naiad.api.ws import (
        broadcast_ha_state,
        broadcast_notification,
        broadcast_sequence_changed,
        broadcast_valve_changed,
    )
    from naiad.api.ws import manager as ws_manager
    from naiad.scheduler import flush_notification_queue, push_notification

    async def _on_run_started(sequence_id: str, triggered_by: str) -> None:
        await broadcast_sequence_changed(sequence_id, "running", triggered_by)

    runner.on_started = _on_run_started

    async def _on_run_notification(message: str, level: str) -> None:
        # Watchdog (and future runner events): push to phones + broadcast in-app.
        await push_notification(ha, config, message, category="abort")
        await broadcast_notification(message, level)

    runner.on_notification = _on_run_notification

    valve_entities = {z.switch: z_id for z_id, z in config.zones.items()}

    async def _valve_state_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        if entity_id not in valve_entities:
            return
        zone_id = valve_entities[entity_id]
        state_val = new_state.get("state", "unknown")
        if state_val in ("on", "off"):
            await broadcast_valve_changed(zone_id, state_val, entity_id)

    ha.subscribe_state_changes(_valve_state_cb)

    recovery_done = False

    async def _ha_connected_cb(connected: bool) -> None:
        nonlocal recovery_done
        await broadcast_ha_state(connected)
        if connected:
            # Deliver anything buffered while HA was unreachable, before any other
            # reconnect work (recovery/reconciliation may itself push notifications).
            await flush_notification_queue(ha, config)
            if runner.any_running():
                # A run is live (reconnect mid-run) — don't interfere with it, but
                # still refresh the fallback max temperature in the background.
                await refresh_fallback_temp_max(config, ha)
                return
            if not recovery_done:
                # First time HA is reachable: recover interrupted runs whose zone
                # window is still open, otherwise close orphaned valves.
                recovery_done = True
                actions = await runner.recover_runs()
                logger.info("Crash recovery: %s", ", ".join(actions))
            else:
                # Later reconnects while idle: close any orphaned valves. A
                # manually/externally opened valve is also closed here, since
                # Naiad treats itself as the authoritative valve controller.
                await runner.reconcile_valves()
                logger.info("Valve reconciliation complete")
            # Recovery/reconciliation done — now populate the fallback max
            # temperature (yesterday's recorded max); the hourly job keeps it fresh.
            await refresh_fallback_temp_max(config, ha)
        else:
            # Do NOT abort a live run on disconnect: the run task does not depend
            # on HA, and aborting cannot physically close the valve anyway (HA is
            # unreachable). A brief blip thus stays transparent — the resilient
            # turn_off succeeds once HA returns, the watchdog still bounds the run,
            # and reconcile-on-reconnect closes anything left open. The ActiveRun
            # record is kept, so a crash during the outage still recovers on boot.
            running = runner.running_run_ids()
            if running:
                logger.warning(
                    "HA connection lost while %s is running — run(s) continue; "
                    "valves will be reconciled when HA returns",
                    ", ".join(running),
                )

    ha.on_connection_change = _ha_connected_cb

    # Start the HA connection only after every callback/subscription is wired, so
    # the first on_connection_change(True) — which drives crash recovery / valve
    # reconciliation — cannot fire before its handler is attached.
    await ha.start()
    logger.info("HA client started", extra={"url": ha_url, "addon": is_addon_context()})

    await stats_publisher.start()

    app.state.config = config
    app.state.ha_client = ha
    app.state.runner = runner
    app.state.scheduler = scheduler
    app.state.tracker = _tracker
    app.state.stats_publisher = stats_publisher
    app.state.session_factory = _session_factory
    app.state.ws_manager = ws_manager

    logger.info("Naiad ready")
    yield

    scheduler.shutdown(wait=False)
    await stats_publisher.stop()
    await ha.stop()
    logger.info("Naiad stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Naiad",
    version=__version__,
    description="Garden irrigation controller for Home Assistant",
    lifespan=_lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(_RequestIDMiddleware)
app.add_middleware(_SecurityHeadersMiddleware)

from naiad.api import (  # noqa: E402
    auth,
    history,
    plans,
    preferences,
    sequences,
    settings,
    system,
    zones,
)
from naiad.api import config as config_api  # noqa: E402
from naiad.api import status as _status  # noqa: E402
from naiad.api import ws as _ws  # noqa: E402

app.include_router(_status.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(sequences.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(config_api.router, prefix="/api")
app.include_router(_ws.router, prefix="/api")

# Serve built frontend (present in Docker image, absent in dev)
_static = Path(__file__).parent.parent / "static"
if _static.is_dir():

    class _SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope: Scope) -> Response:
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", _SPAStaticFiles(directory=str(_static), html=True), name="static")
