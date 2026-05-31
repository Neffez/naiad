import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, col, select

from naiad.api.ws import broadcast_notification, broadcast_sequence_changed
from naiad.config import NOTIFICATION_CATEGORIES, AppConfig, target_service_data
from naiad.domain.factors import compute_factors
from naiad.domain.models import Plan, SequenceOverride, SkippedRun, UserPreference
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import MutexConflict, SequenceRunner, zone_id_of_run
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _master_on(session_factory: SessionFactory) -> bool:
    with session_factory() as session:
        pref = session.get(UserPreference, "master_on")
        return pref is None or pref.value == "1"


# Tolerance for matching a one-off skip to the fire time of a cron run. A cron job
# fires on the minute, so a 2-minute window comfortably absorbs scheduler jitter.
_SKIP_MATCH_TOLERANCE_S = 120.0


def _consume_skip(session_factory: SessionFactory, sequence_id: str, now: datetime) -> bool:
    """Return True if this run was marked to be skipped once (and consume it).

    Also prunes clearly-stale skip records so the table can't grow unbounded.
    """
    now_naive = now.replace(tzinfo=None)
    with session_factory() as session:
        rows = list(
            session.exec(select(SkippedRun).where(SkippedRun.sequence_id == sequence_id)).all()
        )
        hit = False
        changed = False
        for row in rows:
            delta = abs((row.scheduled_at - now_naive).total_seconds())
            if delta <= _SKIP_MATCH_TOLERANCE_S:
                session.delete(row)
                hit = True
                changed = True
            elif row.scheduled_at < now_naive - timedelta(hours=6):
                session.delete(row)  # stale (its occurrence has long passed)
                changed = True
        if changed:
            session.commit()
    return hit


async def push_notification(
    ha: HAClient, config: AppConfig, message: str, *, category: str = "info"
) -> None:
    """Push to every notify target subscribed to ``category`` (``info`` → all).

    Each target chooses its own categories and silent/platform settings.
    """
    targets = config.ha.notify_targets
    if not targets:
        logger.debug("Notify skipped — no notify_targets configured (%s)", message)
        return
    sent = 0
    for target in targets:
        if category in NOTIFICATION_CATEGORIES and category not in target.categories:
            continue
        service = target.service.removeprefix("notify.")
        try:
            await ha.call_service("notify", service, **target_service_data(target, message))
            sent += 1
            logger.info("Notified %s (%s)", target.service, category)
        except Exception:
            logger.warning("Notify failed for '%s'", target.service, exc_info=True)
    if sent == 0:
        logger.debug("No target subscribed to category '%s'", category)


async def refresh_fallback_temp_max(config: AppConfig, ha: HAClient) -> None:
    """Refresh the cached fallback max temperature (yesterday's recorded max).

    Only needed when no forecast max-temperature sensor is configured — that's the
    case where the temperature adjustment falls back to yesterday's max. The
    current temperature is never a good proxy (cold at night), so it isn't used.
    """
    if config.sensors.temperature_max or not config.sensors.temperature:
        return
    tz = ZoneInfo(config.timezone)
    today_local = datetime.now(tz).date()
    start = datetime.combine(today_local - timedelta(days=1), time.min, tzinfo=tz)
    end = datetime.combine(today_local, time.min, tzinfo=tz)
    await ha.refresh_daily_max(
        config.sensors.temperature, start.astimezone(UTC), end.astimezone(UTC)
    )


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

    # A user may skip a single scheduled occurrence; only the matching cron fire
    # consumes it (manual starts and plans don't go through this skip gate).
    if triggered_by == "cron" and _consume_skip(session_factory, sequence_id, datetime.now(UTC)):
        logger.info("Skipped (%s): user skipped this scheduled run", sequence_id)
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
        await push_notification(
            ha, config, f"⚠️ {seq_cfg.label}: Wind — Lauf übersprungen", category="skip"
        )
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
        # Name the sequence that is actually blocking (the running one), not the
        # one we just tried to start.
        running_id = runner.status().sequence_id
        running_cfg = config.sequences.get(running_id) if running_id else None
        running_label = running_cfg.label if running_cfg else (running_id or "?")
        conflict_note = (
            f"⚠️ Zeitplan-Konflikt: {seq_cfg.label} übersprungen — {running_label} läuft noch"
        )
        await push_notification(ha, config, conflict_note, category="skip")
        await broadcast_notification(conflict_note, level="warning")
        return "conflict"

    label_pct = int(round(factors.factor_pct))
    note = f"🌿 {seq_cfg.label} gestartet ({triggered_by}, Faktor {label_pct} %)"
    await push_notification(ha, config, note, category="start")
    # The "running" status is broadcast by the runner's on_started callback once a
    # valve actually opens, so clients never see a run that failed to start.
    await broadcast_notification(note)
    logger.info("Started '%s' via %s (factor=%d%%)", sequence_id, triggered_by, label_pct)
    return "started"


async def _run_zone_job(
    zone_id: str,
    duration_min: float,
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
    triggered_by: str = "plan",
) -> str:
    """Attempt to start a standalone single-zone run. Returns "started",
    "skipped" or "conflict" (same contract as ``_run_sequence_job``).

    A planned zone run waters exactly the requested duration: the weather factor
    is intentionally not applied (it targets one bed for a fixed time). Rain is
    still respected — the live rain listener aborts a running zone.
    """
    zone_cfg = config.zones.get(zone_id)
    if zone_cfg is None or not zone_cfg.switch:
        logger.info("Skipped zone '%s': unknown zone or no switch entity", zone_id)
        return "skipped"

    if not _master_on(session_factory):
        logger.info("Skipped zone '%s': master off", zone_id)
        return "skipped"

    try:
        await runner.start_zone(zone_id, duration_min, triggered_by=triggered_by)
    except MutexConflict as e:
        logger.warning("Conflict for zone '%s': %s", zone_id, e)
        running_id = runner.status().sequence_id
        zid = zone_id_of_run(running_id) if running_id else None
        running_cfg = config.zones.get(zid) if zid else config.sequences.get(running_id or "")
        running_label = running_cfg.label if running_cfg else (running_id or "?")
        conflict_note = (
            f"⚠️ Zeitplan-Konflikt: Zone {zone_cfg.label} übersprungen — {running_label} läuft noch"
        )
        await push_notification(ha, config, conflict_note, category="skip")
        await broadcast_notification(conflict_note, level="warning")
        return "conflict"

    note = f"🌿 Zone {zone_cfg.label} gestartet ({triggered_by}, {int(round(duration_min))} min)"
    await push_notification(ha, config, note, category="start")
    await broadcast_notification(note)
    logger.info("Started zone '%s' via %s (%.0f min)", zone_id, triggered_by, duration_min)
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

        if plan.zone_id is not None:
            duration = float(plan.duration_min) if plan.duration_min is not None else 10.0
            result = await _run_zone_job(
                plan.zone_id,
                duration,
                runner,
                ha,
                config,
                session_factory,
                triggered_by="plan",
            )
        else:
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

    zid = zone_id_of_run(status.sequence_id)
    if zid is not None:
        zone_cfg = config.zones.get(zid)
        label = zone_cfg.label if zone_cfg else zid
    else:
        seq_cfg = config.sequences.get(status.sequence_id)
        label = seq_cfg.label if seq_cfg else status.sequence_id
    logger.info("Rain detected — aborting '%s'", status.sequence_id)

    try:
        seq_id = status.sequence_id
        await runner.stop(reason="rain")
        rain_note = f"🌧 Bewässerung gestoppt: Regen ({label})"
        await push_notification(ha, config, rain_note, category="abort")
        await broadcast_sequence_changed(seq_id, "idle", "rain")
        await broadcast_notification(rain_note, level="warning")
    except Exception:
        logger.exception("Error aborting sequence on rain")


async def _evening_reminder(
    scheduler: AsyncIOScheduler,
    config: AppConfig,
    ha: HAClient,
    session_factory: SessionFactory,
) -> None:
    """Push a summary of the next day's scheduled runs (nightly).

    push_notification gates delivery per target (category "reminder"); we just skip
    the work when nobody is subscribed.
    """
    if not any("reminder" in t.categories for t in config.ha.notify_targets):
        return
    tz = ZoneInfo(config.timezone)
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()
    runs: list[tuple[datetime, str]] = []

    for seq_id, seq_cfg in config.sequences.items():
        if not seq_cfg.enabled:
            continue
        nxt = next_run_for_sequence(scheduler, seq_id)
        if nxt is not None and nxt.astimezone(tz).date() == tomorrow:
            runs.append((nxt.astimezone(tz), seq_cfg.label))

    with session_factory() as session:
        plans = list(session.exec(select(Plan)).all())
    for plan in plans:
        when = plan.scheduled_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        local = when.astimezone(tz)
        if local.date() == tomorrow:
            if plan.zone_id is not None:
                zone_cfg = config.zones.get(plan.zone_id)
                label = zone_cfg.label if zone_cfg else plan.zone_id
            else:
                pseq = config.sequences.get(plan.sequence_id)
                label = pseq.label if pseq else plan.sequence_id
            runs.append((local, f"{label} (geplant)"))

    if runs:
        runs.sort(key=lambda r: r[0])
        lines = "\n".join(f"• {when.strftime('%H:%M')} {label}" for when, label in runs)
        message = "💦🌱 Morgen:\n" + lines
    else:
        message = "💦🌱 Morgen keine Bewässerung geplant."
    await push_notification(ha, config, message, category="reminder")


def next_run_for_sequence(scheduler: AsyncIOScheduler, seq_id: str) -> datetime | None:
    """Earliest upcoming fire time across all cron triggers of a sequence.

    A sequence may have several cron jobs (one per scheduled time), so the next
    run is the minimum of their individual next-run times.
    """
    runs = [
        job.next_run_time
        for job in scheduler.get_jobs()
        if job.id.startswith("cron-") and job.args and job.args[0] == seq_id and job.next_run_time
    ]
    return min(runs) if runs else None


def upcoming_cron_runs(scheduler: AsyncIOScheduler, seq_id: str, until: datetime) -> list[datetime]:
    """All upcoming cron fire times of a sequence up to ``until`` (inclusive).

    A sequence can have several cron times per day, so this enumerates each
    trigger forward instead of returning only the single earliest fire.
    """
    out: list[datetime] = []
    for job in scheduler.get_jobs():
        if not (job.id.startswith("cron-") and job.args and job.args[0] == seq_id):
            continue
        nxt = job.next_run_time
        guard = 0
        while nxt is not None and nxt <= until and guard < 64:
            out.append(nxt)
            nxt = job.trigger.get_next_fire_time(nxt, nxt + timedelta(seconds=1))
            guard += 1
    return out


def _register_reminder_job(
    scheduler: AsyncIOScheduler,
    config: AppConfig,
    ha: HAClient,
    session_factory: SessionFactory,
) -> None:
    """(Re)register the nightly reminder; only when a target wants the reminder."""
    if scheduler.get_job("evening-reminder") is not None:
        scheduler.remove_job("evening-reminder")
    if not any("reminder" in t.categories for t in config.ha.notify_targets):
        return
    try:
        trigger = CronTrigger.from_crontab(
            config.notifications.evening_reminder_cron, timezone=config.timezone
        )
    except Exception:
        logger.warning(
            "Invalid evening_reminder_cron '%s' — reminder disabled",
            config.notifications.evening_reminder_cron,
        )
        return
    scheduler.add_job(
        _evening_reminder,
        trigger=trigger,
        args=[scheduler, config, ha, session_factory],
        id="evening-reminder",
        name="Evening reminder",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info("Evening reminder registered (%s)", config.notifications.evening_reminder_cron)


def _register_sequence_jobs(
    scheduler: AsyncIOScheduler,
    config: AppConfig,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: SessionFactory,
) -> None:
    """(Re)register one cron job per enabled sequence. Existing cron jobs are
    replaced (replace_existing=True), so this is safe to call on config reload."""
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
        for idx, cron in enumerate(seq_cfg.schedule.to_crons()):
            try:
                trigger = CronTrigger.from_crontab(cron, timezone=config.timezone)
            except Exception:
                logger.warning("Sequence '%s': invalid cron '%s' — skipped", seq_id, cron)
                continue
            scheduler.add_job(
                _run_sequence_job,
                trigger=trigger,
                args=[seq_id, runner, ha, config, session_factory],
                kwargs={"triggered_by": "cron"},
                id=f"cron-{seq_id}#{idx}",
                name=f"Cron: {seq_cfg.label}",
                misfire_grace_time=300,
                replace_existing=True,
            )
            logger.info("Cron job registered: '%s' (%s)", seq_id, cron)


def reschedule_sequences(
    scheduler: AsyncIOScheduler,
    config: AppConfig,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: SessionFactory,
) -> None:
    """Drop all sequence cron jobs and re-register them from the current config.

    Called after a configuration change so added/removed/rescheduled/disabled
    sequences take effect without a restart. The plan-tick and rain listener are
    left untouched (they read config by reference).
    """
    for job in scheduler.get_jobs():
        if job.id.startswith("cron-"):
            scheduler.remove_job(job.id)
    _register_sequence_jobs(scheduler, config, runner, ha, session_factory)
    _register_reminder_job(scheduler, config, ha, session_factory)


def setup_scheduler(
    config: AppConfig,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: SessionFactory,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.timezone)

    _register_sequence_jobs(scheduler, config, runner, ha, session_factory)

    scheduler.add_job(
        _plan_tick,
        trigger=IntervalTrigger(seconds=60),
        args=[runner, ha, config, session_factory],
        id="plan-tick",
        name="Plan tick",
        max_instances=1,
        misfire_grace_time=30,
    )

    _register_reminder_job(scheduler, config, ha, session_factory)

    # Keep the fallback max temperature (yesterday's recorded max) fresh so it
    # rolls over shortly after local midnight. The initial fetch is triggered from
    # the HA-connected callback once the socket is up (see main).
    scheduler.add_job(
        refresh_fallback_temp_max,
        trigger=IntervalTrigger(hours=1),
        args=[config, ha],
        id="fallback-temp-max",
        name="Fallback temp max refresh",
        max_instances=1,
        misfire_grace_time=600,
    )

    async def _rain_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        await _on_rain(entity_id, new_state, runner, config, ha)

    ha.subscribe_state_changes(_rain_cb)
    logger.info("Rain listener registered: '%s'", config.sensors.rain)

    return scheduler
