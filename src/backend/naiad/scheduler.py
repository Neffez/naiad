import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, col, select

from naiad.api.ws import broadcast_notification, broadcast_sequence_changed
from naiad.config import NOTIFICATION_CATEGORIES, AppConfig, target_service_data
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
        conflict_note = f"⚠️ Zeitplan-Konflikt: {seq_cfg.label} — läuft bereits"
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
        job = scheduler.get_job(f"cron-{seq_id}")
        nxt = job.next_run_time if job else None
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
            pseq = config.sequences.get(plan.sequence_id)
            label = pseq.label if pseq else plan.sequence_id
            runs.append((local, f"{label} (geplant)"))

    if runs:
        runs.sort(key=lambda r: r[0])
        lines = "\n".join(f"• {when.strftime('%H:%M')} {label}" for when, label in runs)
        message = "🌙 Morgen:\n" + lines
    else:
        message = "🌙 Morgen keine Bewässerung geplant."
    await push_notification(ha, config, message, category="reminder")


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
        trigger = CronTrigger.from_crontab(seq_cfg.schedule.cron, timezone=config.timezone)
        scheduler.add_job(
            _run_sequence_job,
            trigger=trigger,
            args=[seq_id, runner, ha, config, session_factory],
            kwargs={"triggered_by": "cron"},
            id=f"cron-{seq_id}",
            name=f"Cron: {seq_cfg.label}",
            misfire_grace_time=300,
            replace_existing=True,
        )
        logger.info("Cron job registered: '%s' (%s)", seq_id, seq_cfg.schedule.cron)


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

    async def _rain_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        await _on_rain(entity_id, new_state, runner, config, ha)

    ha.subscribe_state_changes(_rain_cb)
    logger.info("Rain listener registered: '%s'", config.sensors.rain)

    return scheduler
