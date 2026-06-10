import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from naiad.api.schemas import StartZoneRequest
from naiad.api.ws import broadcast_sequence_changed
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, get_runner, require_auth
from naiad.domain.preferences import read_master_on
from naiad.domain.sequences import (
    MutexConflict,
    NotRunning,
    SequenceRunner,
    SequenceState,
    ZoneNotFound,
    zone_run_id,
)

router = APIRouter(prefix="/zones", tags=["zones"])
logger = logging.getLogger(__name__)


@router.post("/{zone_id}/start", status_code=202)
async def start_zone(
    zone_id: str,
    body: StartZoneRequest,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Start a single zone immediately for a fixed duration.

    Runs the zone in isolation (not as part of a sequence) for exactly the
    requested minutes — the weather factor is not applied.
    """
    logger.info("Manual zone start requested for '%s'", zone_id)

    def _reject(code: int, detail: str) -> HTTPException:
        logger.info("Zone start of '%s' refused: %s", zone_id, detail)
        return HTTPException(code, detail)

    if zone_id not in config.zones:
        raise _reject(404, f"Zone '{zone_id}' not found")
    if not config.zones[zone_id].switch:
        raise _reject(422, "Zone has no switch entity. Set it in the configuration.")
    if not read_master_on(session):
        raise _reject(422, "Master switch is off")

    try:
        await runner.start_zone(zone_id, float(body.duration_min))
    except ZoneNotFound as e:
        raise _reject(404, f"Zone '{zone_id}' not found") from e
    except MutexConflict as e:
        raise _reject(409, str(e)) from e

    logger.info("Zone '%s' started: %d min", zone_id, body.duration_min)
    # "running" is broadcast by the runner's on_started callback once the valve opens.
    return {"started": zone_id}


@router.post("/{zone_id}/stop", status_code=202)
async def stop_zone(
    zone_id: str,
    _: None = Depends(require_auth),
    runner: SequenceRunner = Depends(get_runner),
) -> dict[str, str]:
    """Stop a standalone single-zone run. Refuses if the zone is on as part of a
    sequence — that is stopped via the sequence."""
    run_id = zone_run_id(zone_id)
    if runner.status_of(run_id).state != SequenceState.RUNNING:
        raise HTTPException(409, f"Zone '{zone_id}' is not running as a standalone run")
    with contextlib.suppress(NotRunning):
        await runner.stop(run_id)
    await broadcast_sequence_changed(run_id, "idle", "manual")
    return {"stopped": zone_id}
