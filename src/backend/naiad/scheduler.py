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
from naiad.config import (
    NOTIFICATION_CATEGORIES,
    AppConfig,
    NotifyTarget,
    target_service_data,
)
from naiad.domain.factors import compute_factors
from naiad.domain.models import (
    Plan,
    QueuedNotification,
    SequenceOverride,
    SkippedRun,
)
from naiad.domain.preferences import read_master_on
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import MutexConflict, SequenceRunner, zone_id_of_run
from naiad.ha_client import HAClient
from naiad.i18n import t

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _master_on(session_factory: SessionFactory) -> bool:
    with session_factory() as session:
        return read_master_on(session)


def _run_label(config: AppConfig, run_id: str | None) -> str:
    """Human label for a run id (real sequence or synthetic single-zone run)."""
    if run_id is None:
        return "?"
    zid = zone_id_of_run(run_id)
    cfg = config.zones.get(zid) if zid else config.sequences.get(run_id)
    return cfg.label if cfg else (zid or run_id)


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


# Hard cap so a long HA outage cannot grow the queue without bound (oldest first).
_QUEUE_MAX_ITEMS = 500


def _utcnow_naive() -> datetime:
    """Current UTC time without tzinfo — matches how datetimes round-trip through
    SQLite (the driver returns naive values), so stored and computed times compare."""
    return datetime.now(UTC).replace(tzinfo=None)


class NotificationQueue:
    """Persists notifications that fail to send while HA is offline and re-delivers
    them on the next (re)connect — including after a restart, since the rows live in
    the database. Entries older than ``notifications.queue_max_hours`` are dropped
    rather than arriving late.

    Bound to a session factory at startup (see ``setup_scheduler``); until then it
    silently drops, so a misconfiguration never crashes a notification path.
    """

    def __init__(self) -> None:
        self._session_factory: SessionFactory | None = None

    def bind(self, session_factory: SessionFactory | None) -> None:
        self._session_factory = session_factory

    def pending_count(self) -> int:
        if self._session_factory is None:
            return 0
        with self._session_factory() as session:
            return len(session.exec(select(QueuedNotification)).all())

    def enqueue(self, target: NotifyTarget, message: str, category: str, config: AppConfig) -> None:
        if config.notifications.queue_max_hours <= 0:
            return  # queuing disabled — drop, preserving the previous behaviour
        if self._session_factory is None:
            logger.warning("Notification queue not bound to a database — dropping (%s)", category)
            return
        with self._session_factory() as session:
            self._prune_stale(session, config)
            session.add(
                QueuedNotification(
                    service=target.service,
                    message=message,
                    category=category,
                    quiet=target.quiet,
                    platform=target.platform,
                    enqueued_at=_utcnow_naive(),
                )
            )
            session.commit()
            self._enforce_cap(session)
            pending = len(session.exec(select(QueuedNotification)).all())
        logger.info(
            "Notification queued for '%s' (%s) — HA unreachable; %d pending",
            target.service,
            category,
            pending,
        )

    def _prune_stale(self, session: Session, config: AppConfig) -> None:
        cutoff = _utcnow_naive() - timedelta(hours=config.notifications.queue_max_hours)
        stale = list(
            session.exec(
                select(QueuedNotification).where(col(QueuedNotification.enqueued_at) < cutoff)
            ).all()
        )
        for row in stale:
            session.delete(row)
        if stale:
            session.commit()
            logger.warning(
                "Dropped %d queued notification(s) older than %sh",
                len(stale),
                config.notifications.queue_max_hours,
            )

    def _enforce_cap(self, session: Session) -> None:
        rows = list(
            session.exec(
                select(QueuedNotification).order_by(col(QueuedNotification.enqueued_at))
            ).all()
        )
        overflow = len(rows) - _QUEUE_MAX_ITEMS
        if overflow > 0:
            for row in rows[:overflow]:
                session.delete(row)
            session.commit()
            logger.warning("Notification queue full — dropped %d oldest item(s)", overflow)

    async def flush(self, ha: HAClient, config: AppConfig) -> None:
        """Re-deliver every queued notification, oldest first: drop the stale ones,
        send the rest, and stop early if HA drops again mid-flush (the remaining rows
        stay in the database for the next reconnect)."""
        if self._session_factory is None:
            return
        with self._session_factory() as session:
            self._prune_stale(session, config)
            rows = list(
                session.exec(
                    select(QueuedNotification).order_by(col(QueuedNotification.enqueued_at))
                ).all()
            )
        delivered = 0
        for row in rows:
            target = NotifyTarget.model_validate(
                {"service": row.service, "quiet": row.quiet, "platform": row.platform}
            )
            if await _deliver(ha, target, row.message):
                self._delete(row.id)
                delivered += 1
                logger.info("Delivered queued notification to '%s' (%s)", row.service, row.category)
            elif not ha.is_connected:
                break  # still offline — keep this and the rest for the next reconnect
            else:
                self._delete(row.id)  # permanent service error (already warned) — drop it
        if delivered:
            logger.info("Flushed %d queued notification(s)", delivered)

    def _delete(self, row_id: int | None) -> None:
        if self._session_factory is None or row_id is None:
            return
        with self._session_factory() as session:
            row = session.get(QueuedNotification, row_id)
            if row is not None:
                session.delete(row)
                session.commit()


_notification_queue = NotificationQueue()


async def _deliver(ha: HAClient, target: NotifyTarget, message: str) -> bool:
    """Attempt one notify call. Returns True on success. On failure while connected
    it logs a warning (a real service error, not retried); while disconnected it
    stays silent so the caller can decide to queue it."""
    try:
        await ha.call_service(
            "notify",
            target.service.removeprefix("notify."),
            **target_service_data(target, message),
        )
        return True
    except Exception:
        if ha.is_connected:
            logger.warning("Notify failed for '%s'", target.service, exc_info=True)
        return False


async def flush_notification_queue(ha: HAClient, config: AppConfig) -> None:
    """Re-deliver notifications buffered during an HA outage. Call on reconnect."""
    await _notification_queue.flush(ha, config)


async def push_notification(
    ha: HAClient, config: AppConfig, message: str, *, category: str = "info"
) -> None:
    """Push to every notify target subscribed to ``category`` (``info`` → all).

    Each target chooses its own categories and silent/platform settings. Sends that
    fail because HA is unreachable are queued and re-delivered on reconnect (see
    NotificationQueue); real service errors are logged and dropped.
    """
    targets = config.ha.notify_targets
    if not targets:
        logger.debug("Notify skipped — no notify_targets configured (%s)", message)
        return
    sent = 0
    queued = 0
    for target in targets:
        if category in NOTIFICATION_CATEGORIES and category not in target.categories:
            continue
        if await _deliver(ha, target, message):
            sent += 1
            logger.info("Notified %s (%s)", target.service, category)
        elif not ha.is_connected:
            _notification_queue.enqueue(target, message, category, config)
            queued += 1
        # else: real service error while connected — already warned in _deliver
    if sent == 0 and queued == 0:
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
            ha, config, t("skip.wind", config.language, label=seq_cfg.label), category="skip"
        )
        return "skipped"

    with session_factory() as session:
        factors = compute_factors(snapshot, config, session)

    if factors.season_off:
        logger.info("Skipped (%s): season off", sequence_id)
        return "skipped"

    # A computed factor of 0 % (e.g. forecast rain at/above zero_above_mm) means
    # "don't water" — skip rather than fall back to the range floor. This gate is
    # on the automatic path only (cron + plans both reach here); a manual start
    # goes through the API and is intentionally not subject to it.
    if round(factors.factor_pct) == 0:
        logger.info("Skipped (%s): watering factor is 0%%", sequence_id)
        await push_notification(
            ha, config, t("skip.zero_factor", config.language, label=seq_cfg.label), category="skip"
        )
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
        # Name the run that is actually blocking (the one reserving a shared zone),
        # not the one we just tried to start.
        running_id = runner.conflicting_run(seq_cfg.zones)
        running_label = _run_label(config, running_id)
        conflict_note = t(
            "skip.conflict_sequence", config.language, label=seq_cfg.label, running=running_label
        )
        await push_notification(ha, config, conflict_note, category="skip")
        await broadcast_notification(conflict_note, level="warning")
        return "conflict"

    label_pct = int(round(factors.factor_pct))
    note = t(
        "start.sequence",
        config.language,
        label=seq_cfg.label,
        trigger=t(f"trigger.{triggered_by}", config.language),
        pct=label_pct,
    )
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
        running_id = runner.conflicting_run([zone_id])
        running_label = _run_label(config, running_id)
        conflict_note = t(
            "skip.conflict_zone", config.language, label=zone_cfg.label, running=running_label
        )
        await push_notification(ha, config, conflict_note, category="skip")
        await broadcast_notification(conflict_note, level="warning")
        return "conflict"

    note = t(
        "start.zone",
        config.language,
        label=zone_cfg.label,
        trigger=t(f"trigger.{triggered_by}", config.language),
        minutes=int(round(duration_min)),
    )
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

    # Abort every live run. Each run is independent, so a failure on one must not
    # prevent aborting the others.
    for run_id in runner.running_run_ids():
        label = _run_label(config, run_id)
        logger.info("Rain detected — aborting '%s'", run_id)
        try:
            await runner.stop(run_id, reason="rain")
            rain_note = t("abort.rain", config.language, label=label)
            await push_notification(ha, config, rain_note, category="abort")
            await broadcast_sequence_changed(run_id, "idle", "rain")
            await broadcast_notification(rain_note, level="warning")
        except Exception:
            logger.exception("Error aborting run '%s' on rain", run_id)

    # Paused runs (resume snapshots) would otherwise survive the rain and could be
    # resumed later. Discard them all so rain during a pause is honored too.
    for cleared in runner.clear_paused_snapshots():
        seq_cfg = config.sequences.get(cleared)
        label = seq_cfg.label if seq_cfg else cleared
        logger.info("Rain detected — discarding paused run '%s'", cleared)
        rain_note = t("abort.paused_rain", config.language, label=label)
        await push_notification(ha, config, rain_note, category="abort")
        await broadcast_sequence_changed(cleared, "idle", "rain")
        await broadcast_notification(rain_note, level="warning")


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
            runs.append((local, t("reminder.planned", config.language, label=label)))

    if runs:
        runs.sort(key=lambda r: r[0])
        lines = "\n".join(
            t("reminder.line", config.language, time=when.strftime("%H:%M"), label=label)
            for when, label in runs
        )
        message = t("reminder.header", config.language) + "\n" + lines
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

    # Back the offline notification queue with the app database so buffered
    # notifications survive a restart and flush on the next HA (re)connect.
    _notification_queue.bind(session_factory)

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
