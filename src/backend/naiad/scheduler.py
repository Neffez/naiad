import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, col, select

from naiad.api.ws import broadcast_notification, broadcast_sequence_changed
from naiad.config import AppConfig
from naiad.domain.factors import compute_factors
from naiad.domain.models import Plan, SequenceOverride, UserPreference
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import MutexConflict, SequenceRunner
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _master_on(session_factory: SessionFactory) -> bool:
    with session_factory() as session:
        pref = session.get(UserPreference, "master_on")
        return pref is None or pref.value == "1"


async def _notify(ha: HAClient, config: AppConfig, message: str) -> None:
    if not config.ha.notify_targets:
        return
    for target in config.ha.notify_targets:
        service = target.removeprefix("notify.")
        try:
            await ha.call_service("notify", service, message=message)
        except Exception:
            logger.warning("Notify failed for '%s'", target)


async def _run_sequence_job(
    sequence_id: str,
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
    triggered_by: str = "cron",
    override_min: float | None = None,
) -> str:
    """Attempt to start a sequence. Returns "started", "skipped" or "conflict".

    A "conflict" is transient (another sequence is running) and the caller may
    retry; "skipped" is a deterministic refusal (disabled/paused/master/wind/season).
    """
    seq_cfg = config.sequences.get(sequence_id)
    if seq_cfg is None or not seq_cfg.enabled:
        return "skipped"

    with session_factory() as session:
        seq_override = session.get(SequenceOverride, sequence_id)
    if seq_override and seq_override.paused:
        logger.info("Skipped (%s): paused via override", sequence_id)
        return "skipped"

    if not _master_on(session_factory):
        logger.info("Skipped (%s): master off", sequence_id)
        return "skipped"

    snapshot = read_sensor_snapshot(ha, config)

    if seq_cfg.wind_blocks and snapshot.wind_on:
        logger.info("Skipped (%s): wind blocked", sequence_id)
        await _notify(ha, config, f"⚠️ {seq_cfg.label}: Wind — Lauf übersprungen")
        return "skipped"

    with session_factory() as session:
        factors = compute_factors(snapshot, config, session)

    if factors.season_off:
        logger.info("Skipped (%s): season off", sequence_id)
        return "skipped"

    if factors.sensors_unavailable:
        logger.warning(
            "Starting '%s' with unavailable sensors %s — rain/temp adjustment may be incomplete",
            sequence_id,
            factors.sensors_unavailable,
        )

    try:
        await runner.start(
            sequence_id,
            factor_pct=factors.factor_pct,
            override_min=override_min,
            triggered_by=triggered_by,
        )
    except MutexConflict as e:
        logger.warning("Conflict for '%s': %s", sequence_id, e)
        conflict_note = f"⚠️ Zeitplan-Konflikt: {seq_cfg.label} — läuft bereits"
        await _notify(ha, config, conflict_note)
        await broadcast_notification(conflict_note, level="warning")
        return "conflict"

    label_pct = int(round(factors.factor_pct))
    note = f"🌿 {seq_cfg.label} gestartet ({triggered_by}, Faktor {label_pct} %)"
    await _notify(ha, config, note)
    # The "running" status is broadcast by the runner's on_started callback once a
    # valve actually opens, so clients never see a run that failed to start.
    await broadcast_notification(note)
    logger.info("Started '%s' via %s (factor=%d%%)", sequence_id, triggered_by, label_pct)
    return "started"


async def _plan_tick(
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
) -> None:
    now = datetime.now(UTC)

    with session_factory() as session:
        due: list[Plan] = list(
            session.exec(
                select(Plan).where(Plan.scheduled_at <= now).order_by(col(Plan.scheduled_at))
            ).all()
        )

    for plan in due:
        with session_factory() as session:
            if session.get(Plan, plan.id) is None:
                continue  # already consumed

        override_min = float(plan.duration_min) if plan.duration_min is not None else None
        result = await _run_sequence_job(
            plan.sequence_id,
            runner,
            ha,
            config,
            session_factory,
            triggered_by="plan",
            override_min=override_min,
        )

        # Keep the plan on a transient conflict so the next tick retries it;
        # drop it once it has started or was deterministically skipped.
        if result == "conflict":
            continue
        with session_factory() as session:
            db_plan = session.get(Plan, plan.id)
            if db_plan is not None:
                session.delete(db_plan)
                session.commit()


async def _on_rain(
    entity_id: str,
    new_state: dict[str, Any],
    runner: SequenceRunner,
    config: AppConfig,
    ha: HAClient,
) -> None:
    if entity_id != config.sensors.rain:
        return
    if new_state.get("state") != "on":
        return

    status = runner.status()
    if status.sequence_id is None:
        return

    seq_cfg = config.sequences.get(status.sequence_id)
    label = seq_cfg.label if seq_cfg else status.sequence_id
    logger.info("Rain detected — aborting '%s'", status.sequence_id)

    try:
        seq_id = status.sequence_id
        await runner.stop(reason="rain")
        rain_note = f"🌧 Bewässerung gestoppt: Regen ({label})"
        await _notify(ha, config, rain_note)
        await broadcast_sequence_changed(seq_id, "idle", "rain")
        await broadcast_notification(rain_note, level="warning")
    except Exception:
        logger.exception("Error aborting sequence on rain")


def setup_scheduler(
    config: AppConfig,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: SessionFactory,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.timezone)

    for seq_id, seq_cfg in config.sequences.items():
        if not seq_cfg.enabled:
            continue
        if seq_cfg.watchdog_min <= seq_cfg.basis_min_per_zone:
            logger.warning(
                "Sequence '%s': watchdog_min (%s) <= basis_min_per_zone (%s) — the watchdog "
                "will abort normal runs before they finish. Raise watchdog_min.",
                seq_id,
                seq_cfg.watchdog_min,
                seq_cfg.basis_min_per_zone,
            )
        trigger = CronTrigger.from_crontab(seq_cfg.schedule.cron, timezone=config.timezone)
        scheduler.add_job(
            _run_sequence_job,
            trigger=trigger,
            args=[seq_id, runner, ha, config, session_factory],
            kwargs={"triggered_by": "cron"},
            id=f"cron-{seq_id}",
            name=f"Cron: {seq_cfg.label}",
            misfire_grace_time=300,
        )
        logger.info("Cron job registered: '%s' (%s)", seq_id, seq_cfg.schedule.cron)

    scheduler.add_job(
        _plan_tick,
        trigger=IntervalTrigger(seconds=60),
        args=[runner, ha, config, session_factory],
        id="plan-tick",
        name="Plan tick",
        max_instances=1,
        misfire_grace_time=30,
    )

    async def _rain_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        await _on_rain(entity_id, new_state, runner, config, ha)

    ha.subscribe_state_changes(_rain_cb)
    logger.info("Rain listener registered: '%s'", config.sensors.rain)

    return scheduler
