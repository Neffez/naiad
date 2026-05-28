import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.base import BaseHTTPMiddleware

from naiad.config import load_config
from naiad.database import create_tables, get_engine
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.drivers.ha_driver import HAEntityDriver
from naiad.ha_client import HAClient
from naiad.scheduler import setup_scheduler

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
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs", "pathname",
            "process", "processName", "relativeCreated", "thread", "threadName",
            "exc_info", "exc_text", "stack_info", "message", "taskName",
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


# ── Request-ID middleware ─────────────────────────────────────────────────────

class _RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        req_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# ── Lifespan ──────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    _setup_logging()
    logger.info("Naiad starting")

    config = load_config()
    logger.info(
        "Config loaded", extra={"zones": len(config.zones), "sequences": len(config.sequences)}
    )

    create_tables()
    logger.info("Database tables ready")

    ha = HAClient(url=config.ha.url, token=config.ha.token)
    await ha.start()
    logger.info("HA client started", extra={"url": config.ha.url})

    def _session_factory() -> Session:
        return Session(get_engine())

    driver = HAEntityDriver(ha)
    runner = SequenceRunner(config, driver, _session_factory)
    _tracker = LiterTracker(ha, config, _session_factory, runner.is_managed)

    scheduler = setup_scheduler(config, runner, ha, _session_factory)
    scheduler.start()
    logger.info("Scheduler started (%d jobs)", len(scheduler.get_jobs()))

    from naiad.api.ws import broadcast_ha_state, broadcast_valve_changed, manager as ws_manager

    valve_entities = {z.switch: z_id for z_id, z in config.zones.items()}

    async def _valve_state_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        if entity_id not in valve_entities:
            return
        zone_id = valve_entities[entity_id]
        state_val = new_state.get("state", "unknown")
        if state_val in ("on", "off"):
            await broadcast_valve_changed(zone_id, state_val, entity_id)

    ha.subscribe_state_changes(_valve_state_cb)

    async def _ha_connected_cb(connected: bool) -> None:
        await broadcast_ha_state(connected)

    ha.on_connection_change = _ha_connected_cb

    app.state.config = config
    app.state.ha_client = ha
    app.state.runner = runner
    app.state.scheduler = scheduler
    app.state.ws_manager = ws_manager

    logger.info("Naiad ready")
    yield

    scheduler.shutdown(wait=False)
    await ha.stop()
    logger.info("Naiad stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Naiad",
    version="0.1.0",
    description="Garden irrigation controller for Home Assistant",
    lifespan=_lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(_RequestIDMiddleware)

from naiad.api import auth, history, plans, preferences, sequences, settings, system  # noqa: E402
from naiad.api import status as _status  # noqa: E402
from naiad.api import ws as _ws  # noqa: E402

app.include_router(_status.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(sequences.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(_ws.router, prefix="/api")

# Serve built frontend (present in Docker image, absent in dev)
_static = Path(__file__).parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
