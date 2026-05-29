from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from naiad.api.schemas import (
    CurrentRunResponse,
    SequenceStateResponse,
    StartSequenceRequest,
    ZoneSummaryResponse,
)
from naiad.api.ws import broadcast_sequence_changed
from naiad.config import AppConfig
from naiad.database import get_session
from naiad.dependencies import get_config, get_ha_client, get_runner, get_scheduler, require_auth
from naiad.domain.factors import FactorResult, compute_factors
from naiad.domain.models import ResumeSnapshot, SequenceOverride
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import MutexConflict, NotRunning, SequenceRunner, SequenceState
from naiad.ha_client import HAClient

router = APIRouter(prefix="/sequences", tags=["sequences"])


def _master_on(session: Session) -> bool:
    from naiad.domain.models import UserPreference

    pref = session.get(UserPreference, "master_on")
    return pref is None or pref.value == "1"


def _sequence_status(
    seq_id: str,
    runner: SequenceRunner,
    session: Session,
    config: AppConfig,
) -> str:
    seq_cfg = config.sequences[seq_id]
    if not seq_cfg.enabled:
        return "disabled"
    if runner.status().sequence_id == seq_id:
        return SequenceState.RUNNING
    snap = session.get(ResumeSnapshot, 1)
    if snap and snap.sequence_id == seq_id:
        return SequenceState.PAUSED
    override = session.get(SequenceOverride, seq_id)
    if override and override.paused:
        return "skipped"
    return SequenceState.IDLE


def _get_next_run_at(scheduler: AsyncIOScheduler, seq_id: str) -> datetime | None:
    job = scheduler.get_job(f"cron-{seq_id}")
    if job is None:
        return None
    next_run: datetime | None = job.next_run_time
    return next_run


def _build_current_run(
    runner: SequenceRunner,
    seq_id: str,
    config: AppConfig,
) -> CurrentRunResponse | None:
    run_status = runner.status()
    if run_status.sequence_id != seq_id or run_status.current_zone is None:
        return None

    zone = run_status.current_zone
    now = datetime.now(UTC)
    elapsed_min = (now - zone.started_at).total_seconds() / 60.0
    remaining_min = max(0.0, zone.duration_min - elapsed_min)
    zone_cfg = config.zones.get(zone.zone_id)
    zone_label = zone_cfg.label if zone_cfg else zone.zone_id

    return CurrentRunResponse(
        zone_id=zone.zone_id,
        zone_label=zone_label,
        started_at=zone.started_at,
        elapsed_min=round(elapsed_min, 2),
        remaining_min=round(remaining_min, 2),
        total_min=zone.duration_min,
        triggered_by=run_status.triggered_by,
    )


def _build_state(
    seq_id: str,
    runner: SequenceRunner,
    session: Session,
    config: AppConfig,
    ha: HAClient,
    scheduler: AsyncIOScheduler,
    factors: FactorResult,
) -> SequenceStateResponse:
    seq_cfg = config.sequences[seq_id]
    status = _sequence_status(seq_id, runner, session, config)
    override = session.get(SequenceOverride, seq_id)

    factor_pct = int(round(factors.factor_pct))

    notes: list[str] = []
    if factors.season_off:
        notes.append("Season off")
    if factors.wind_on and seq_cfg.wind_blocks:
        notes.append("Wind blocked")
    if factors.rain_factor_pct < 100:
        notes.append(f"Rain factor: {int(factors.rain_factor_pct)}%")
    if abs(factors.temp_delta_pct) >= 5:
        sign = "+" if factors.temp_delta_pct > 0 else ""
        notes.append(f"Temp: {sign}{int(factors.temp_delta_pct)}%")
    factor_note = "; ".join(notes) if notes else None

    zones = []
    for zone_id in seq_cfg.zones:
        z = config.zones[zone_id]
        raw_state = ha.get_state_value(z.switch)
        valve_state = "on" if raw_state == "on" else ("off" if raw_state == "off" else "unknown")
        zones.append(ZoneSummaryResponse(id=zone_id, label=z.label, valve_state=valve_state))

    basis_override = override.basis_min_per_zone if override else None
    effective_basis = (
        basis_override if basis_override is not None else int(seq_cfg.basis_min_per_zone)
    )

    return SequenceStateResponse(
        id=seq_id,
        label=seq_cfg.label,
        status=str(status),
        enabled=seq_cfg.enabled,
        paused=bool(override.paused) if override else False,
        factor_pct=factor_pct,
        factor_note=factor_note,
        schedule_label=seq_cfg.schedule.cron,
        next_run_at=_get_next_run_at(scheduler, seq_id),
        zones=zones,
        basis_min_per_zone=effective_basis,
        current_run=_build_current_run(runner, seq_id, config),
    )


@router.get("", response_model=list[SequenceStateResponse])
async def list_sequences(
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
) -> list[SequenceStateResponse]:
    # Factors are sequence-independent — compute the sensor snapshot once.
    factors = compute_factors(read_sensor_snapshot(ha, config), config, session)
    return [
        _build_state(seq_id, runner, session, config, ha, scheduler, factors)
        for seq_id in config.sequences
    ]


@router.get("/{sequence_id}", response_model=SequenceStateResponse)
async def get_sequence(
    sequence_id: str,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
    scheduler: AsyncIOScheduler = Depends(get_scheduler),
) -> SequenceStateResponse:
    if sequence_id not in config.sequences:
        raise HTTPException(404, f"Sequence '{sequence_id}' not found")
    factors = compute_factors(read_sensor_snapshot(ha, config), config, session)
    return _build_state(sequence_id, runner, session, config, ha, scheduler, factors)


@router.post("/{sequence_id}/start", status_code=202)
async def start_sequence(
    sequence_id: str,
    body: StartSequenceRequest | None = None,
    _: None = Depends(require_auth),
    config: AppConfig = Depends(get_config),
    runner: SequenceRunner = Depends(get_runner),
    ha: HAClient = Depends(get_ha_client),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if sequence_id not in config.sequences:
        raise HTTPException(404, f"Sequence '{sequence_id}' not found")

    seq_cfg = config.sequences[sequence_id]
    if not seq_cfg.enabled:
        raise HTTPException(422, "Sequence is disabled")

    seq_override = session.get(SequenceOverride, sequence_id)
    if seq_override and seq_override.paused:
        raise HTTPException(422, "Sequence is paused (skipped)")

    if not _master_on(session):
        raise HTTPException(422, "Master switch is off")

    snapshot = read_sensor_snapshot(ha, config)
    if seq_cfg.wind_blocks and snapshot.wind_on:
        raise HTTPException(422, "Wind sensor active — sequence is wind-blocked")

    factors = compute_factors(snapshot, config, session)
    override_min = float(body.duration_min) if body and body.duration_min is not None else None

    try:
        await runner.start(sequence_id, factor_pct=factors.factor_pct, override_min=override_min)
    except MutexConflict as e:
        raise HTTPException(409, str(e)) from e

    # "running" is broadcast by the runner's on_started callback once a valve opens.
    return {"started": sequence_id}


@router.post("/{sequence_id}/pause", status_code=202)
async def pause_sequence(
    sequence_id: str,
    _: None = Depends(require_auth),
    runner: SequenceRunner = Depends(get_runner),
) -> dict[str, str]:
    status = runner.status()
    if status.sequence_id != sequence_id:
        raise HTTPException(409, f"Sequence '{sequence_id}' is not currently running")
    try:
        await runner.pause()
    except NotRunning as e:
        raise HTTPException(409, str(e)) from e
    await broadcast_sequence_changed(sequence_id, "paused", "manual")
    return {"paused": sequence_id}


@router.post("/{sequence_id}/stop", status_code=202)
async def stop_sequence(
    sequence_id: str,
    _: None = Depends(require_auth),
    runner: SequenceRunner = Depends(get_runner),
) -> dict[str, str]:
    status = runner.status()
    if status.sequence_id != sequence_id:
        raise HTTPException(409, f"Sequence '{sequence_id}' is not currently running")
    try:
        await runner.stop()
    except NotRunning as e:
        raise HTTPException(409, str(e)) from e
    await broadcast_sequence_changed(sequence_id, "idle", "manual")
    return {"stopped": sequence_id}
