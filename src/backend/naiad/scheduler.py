import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, col, func, select

from naiad.api.ws import broadcast_notification, broadcast_sequence_changed
from naiad.config import (
    NOTIFICATION_CATEGORIES,
    AppConfig,
    NotifyTarget,
    SequenceConfig,
    target_service_data,
)
from naiad.domain.factors import FactorResult, compute_factors, merge_factor_config
from naiad.domain.models import (
    DecisionLog,
    DeferredCronRun,
    FactorOverride,
    Plan,
    QueuedNotification,
    SequenceOverride,
    SkippedRun,
)
from naiad.domain.preferences import read_master_on
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import (
    MutexConflict,
    RunnerBusy,
    SequenceRunner,
    SequenceStatus,
    zone_id_of_run,
)
from naiad.ha_client import HAClient
from naiad.i18n import t

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
_DEFERRED_CRON_TTL = timedelta(minutes=15)


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

# Decision-log rows older than this are pruned on every insert, keeping the table
# bounded (a handful of rows per day) without a separate cleanup job.
_DECISION_LOG_RETENTION_DAYS = 365


def _log_decision(
    session_factory: SessionFactory,
    sequence_id: str,
    triggered_by: str,
    decision: str,
    reason: str | None = None,
    factors: FactorResult | None = None,
) -> None:
    """Persist one decision-log row ("why did/didn't it water?").

    The log is auxiliary: a write failure must never block or break the
    watering path, so any exception is swallowed after logging it.
    """
    try:
        with session_factory() as session:
            cutoff = _utcnow_naive() - timedelta(days=_DECISION_LOG_RETENTION_DAYS)
            for stale in session.exec(
                select(DecisionLog).where(col(DecisionLog.created_at) < cutoff)
            ).all():
                session.delete(stale)
            entry = DecisionLog(
                sequence_id=sequence_id,
                triggered_by=triggered_by,
                decision=decision,
                reason=reason,
                created_at=_utcnow_naive(),
            )
            if factors is not None:
                entry.factor_pct = factors.factor_pct
                entry.temp_delta_pct = factors.temp_delta_pct
                entry.rain_factor_pct = factors.rain_factor_pct
                entry.temp_c = factors.temp_input_c
                entry.rain_today_mm = factors.rain_today_mm
                entry.rain_tomorrow_mm = factors.rain_tomorrow_mm
                entry.rain_prob_today_pct = factors.rain_prob_today_pct
                entry.rain_prob_tomorrow_pct = factors.rain_prob_tomorrow_pct
                entry.rain_credit_mm = factors.rain_credit_mm
                entry.rain_mode = factors.rain_mode
                entry.manual_factor = factors.manual
            session.add(entry)
            session.commit()
    except Exception:
        logger.exception("Failed to write decision log for '%s'", sequence_id)


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
            return self._count(session)

    @staticmethod
    def _count(session: Session) -> int:
        return int(session.exec(select(func.count()).select_from(QueuedNotification)).one())

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
            pending = self._count(session)
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
        overflow = self._count(session) - _QUEUE_MAX_ITEMS
        if overflow > 0:
            oldest = session.exec(
                select(QueuedNotification)
                .order_by(col(QueuedNotification.enqueued_at))
                .limit(overflow)
            ).all()
            for row in oldest:
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


async def refresh_rain_forecast_max(
    config: AppConfig, ha: HAClient, session_factory: SessionFactory | None = None
) -> None:
    """Refresh the cached daily-max for the precipitation forecast sensors.

    The forecast for the day changes as it progresses (e.g. 5mm in the morning,
    35mm at noon, 10mm in the evening). Reading only the current value means an
    evening drop would restart irrigation that the noon peak had correctly stopped.
    Caching the maximum the forecast reached since local midnight lets the rain
    factor scale to the worst forecast seen today (see ``read_sensor_snapshot``).

    Also refreshes the rain-confirmed peak for the opt-in ``confirm_with_rain_sensor``
    gate (see ``refresh_rain_confirmed_peak``).
    """
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    start_utc, now_utc = start.astimezone(UTC), now.astimezone(UTC)
    for entity_id in (
        config.sensors.precipitation_today,
        config.sensors.precipitation_tomorrow,
        config.sensors.precipitation_prob_today,
        config.sensors.precipitation_prob_tomorrow,
    ):
        if entity_id:
            await ha.refresh_daily_max(entity_id, start_utc, now_utc)
    await refresh_rain_confirmed_peak(config, ha)
    await refresh_recent_rain_credit(config, ha, session_factory)
    await refresh_et0_balance(config, ha, session_factory)


async def refresh_recent_rain_credit(
    config: AppConfig, ha: HAClient, session_factory: SessionFactory | None = None
) -> None:
    """Refresh the multi-day actual-rain credit used by water-balance mode."""
    entity_id = config.sensors.precipitation_actual
    if not entity_id:
        return
    rain_cfg = config.factors.rain
    if session_factory is not None:
        with session_factory() as session:
            _temp_cfg, rain_cfg = merge_factor_config(config, session.get(FactorOverride, 1))
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    start = datetime.combine(
        now.date() - timedelta(days=max(0, rain_cfg.water_balance_days - 1)),
        time.min,
        tzinfo=tz,
    )
    await ha.refresh_recent_rain_credit(
        entity_id,
        start.astimezone(UTC),
        now.astimezone(UTC),
        rain_cfg.water_balance_decay,
        config.sensors.rain if rain_cfg.confirm_with_rain_sensor else None,
    )


async def refresh_et0_balance(
    config: AppConfig, ha: HAClient, session_factory: SessionFactory | None = None
) -> None:
    """Refresh the ET₀ soil water balance used by the et0 rain mode.

    Builds the local-day windows (the ``water_balance_days`` most recent days,
    today's partial day last) and delegates the history math to
    ``HAClient.refresh_et0_balance``. A no-op unless the effective rain mode is
    ``et0`` so the extra recorder fetches only happen when the mode is in use.
    """
    rain_cfg = config.factors.rain
    if session_factory is not None:
        with session_factory() as session:
            _temp_cfg, rain_cfg = merge_factor_config(config, session.get(FactorOverride, 1))
    if rain_cfg.mode != "et0":
        return
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    day_bounds: list[tuple[datetime, datetime]] = []
    days_of_year: list[int] = []
    for offset in range(rain_cfg.water_balance_days - 1, 0, -1):
        day = now.date() - timedelta(days=offset)
        start = datetime.combine(day, time.min, tzinfo=tz)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
        day_bounds.append((start.astimezone(UTC), end.astimezone(UTC)))
        days_of_year.append(day.timetuple().tm_yday)
    today_start = datetime.combine(now.date(), time.min, tzinfo=tz)
    day_bounds.append((today_start.astimezone(UTC), now.astimezone(UTC)))
    days_of_year.append(now.date().timetuple().tm_yday)
    await ha.refresh_et0_balance(
        day_bounds=day_bounds,
        days_of_year=days_of_year,
        rain_entity=config.sensors.precipitation_actual or None,
        temperature_entity=config.sensors.temperature or None,
        et0_entity=config.sensors.et0 or None,
        reservoir_mm=rain_cfg.et0_reservoir_mm,
        fallback_decay=rain_cfg.water_balance_decay,
        confirm_rain_entity=(config.sensors.rain if rain_cfg.confirm_with_rain_sensor else None),
    )


async def refresh_rain_confirmed_peak(config: AppConfig, ha: HAClient) -> None:
    """Recompute today's rain-confirmed peak for the *today* forecast sensors.

    For the ``confirm_with_rain_sensor`` gate: caches the highest forecast value that
    coincided with the binary rain sensor actually being on today, so a forecast spike
    that never produced real rain does not keep suppressing irrigation. Run on the
    hourly/reconnect cadence and on rain transitions; only today's sensors are
    meaningful (tomorrow has not happened yet)."""
    if not config.sensors.rain:
        return
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    await ha.refresh_rain_confirmed_peak(
        [config.sensors.precipitation_today, config.sensors.precipitation_prob_today],
        config.sensors.rain,
        start.astimezone(UTC),
        now.astimezone(UTC),
    )


async def run_sequence_job(
    sequence_id: str,
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
    triggered_by: str = "cron",
    override_min: float | None = None,
    consume_skip: bool = True,
) -> str:
    """Attempt to start a sequence. Returns "started", "skipped", "busy" or "conflict".

    "busy" means valve safety work is active; "conflict" means another sequence
    reserves a valve. Both are transient. "skipped" is a deterministic refusal.

    Shared gate path for every automatic start (cron, plans, MQTT commands):
    paused override, master switch, wind block, season, zero factor, and the
    runner's own safety locks all apply here. Every deterministic outcome
    (started/skipped) is recorded in the decision log; transient busy/conflict
    outcomes are not — their retry produces the row.
    """
    seq_cfg = config.sequences.get(sequence_id)
    if seq_cfg is None or not seq_cfg.enabled:
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "disabled")
        return "skipped"

    # A user may skip a single scheduled occurrence; only the matching cron fire
    # consumes it (manual starts and plans don't go through this skip gate).
    if (
        triggered_by == "cron"
        and consume_skip
        and _consume_skip(session_factory, sequence_id, datetime.now(UTC))
    ):
        logger.info("Skipped (%s): user skipped this scheduled run", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "user_skipped")
        return "skipped"

    with session_factory() as session:
        seq_override = session.get(SequenceOverride, sequence_id)
    if seq_override and seq_override.paused:
        logger.info("Skipped (%s): paused via override", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "paused")
        return "skipped"

    if not _master_on(session_factory):
        logger.info("Skipped (%s): master off", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "master_off")
        return "skipped"

    snapshot = read_sensor_snapshot(ha, config)
    # Computed before the wind gate (it has no side effects) so a wind skip is
    # logged with the factor inputs it would have used.
    with session_factory() as session:
        factors = compute_factors(snapshot, config, session)

    if seq_cfg.wind_blocks and snapshot.wind_on:
        logger.info("Skipped (%s): wind blocked", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "wind", factors)
        await push_notification(
            ha, config, t("skip.wind", config.language, label=seq_cfg.label), category="skip"
        )
        return "skipped"

    if factors.season_off:
        logger.info("Skipped (%s): season off", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "season_off", factors)
        return "skipped"

    # Frost lockout: a forecast daily minimum below the threshold skips the run
    # (pipe protection in the shoulder seasons). An unreadable sensor never
    # blocks watering — the gate is simply not evaluated.
    if (
        config.frost.enabled
        and snapshot.min_temperature_c is not None
        and snapshot.min_temperature_c < config.frost.threshold_c
    ):
        logger.info(
            "Skipped (%s): frost lockout (min %.1f °C < %.1f °C)",
            sequence_id,
            snapshot.min_temperature_c,
            config.frost.threshold_c,
        )
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "frost", factors)
        await push_notification(
            ha,
            config,
            t(
                "skip.frost",
                config.language,
                label=seq_cfg.label,
                temp=round(snapshot.min_temperature_c, 1),
            ),
            category="skip",
        )
        return "skipped"

    # Cistern guard: a level below the configured minimum skips the run (dry-run
    # protection for the pump). Same sensor semantics as the frost gate.
    if (
        config.cistern.enabled
        and snapshot.cistern_level is not None
        and snapshot.cistern_level < config.cistern.min_level
    ):
        logger.info(
            "Skipped (%s): cistern level %.1f below minimum %.1f",
            sequence_id,
            snapshot.cistern_level,
            config.cistern.min_level,
        )
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "cistern_low", factors)
        await push_notification(
            ha, config, t("skip.cistern", config.language, label=seq_cfg.label), category="skip"
        )
        return "skipped"

    # A computed factor of 0 % (e.g. forecast rain at/above zero_above_mm) means
    # "don't water" — skip rather than fall back to the range floor. This gate is
    # on the automatic path only (cron + plans both reach here); a manual start
    # goes through the API and is intentionally not subject to it.
    if round(factors.factor_pct) == 0:
        logger.info("Skipped (%s): watering factor is 0%%", sequence_id)
        _log_decision(session_factory, sequence_id, triggered_by, "skipped", "zero_factor", factors)
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

    label_pct = int(round(factors.factor_pct))
    note = t(
        "start.sequence",
        config.language,
        label=seq_cfg.label,
        trigger=t(f"trigger.{triggered_by}", config.language),
        pct=label_pct,
    )
    try:
        await runner.start(
            sequence_id,
            factor_pct=factors.factor_pct,
            override_min=override_min,
            triggered_by=triggered_by,
            started_notification=note,
        )
    except RunnerBusy as e:
        logger.info("Deferred '%s': %s", sequence_id, e)
        return "busy"
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

    logger.info("Accepted '%s' via %s (factor=%d%%)", sequence_id, triggered_by, label_pct)
    _log_decision(session_factory, sequence_id, triggered_by, "started", None, factors)
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
    "skipped", "busy" or "conflict" (same contract as ``run_sequence_job``).

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

    note = t(
        "start.zone",
        config.language,
        label=zone_cfg.label,
        trigger=t(f"trigger.{triggered_by}", config.language),
        minutes=int(round(duration_min)),
    )
    try:
        await runner.start_zone(
            zone_id,
            duration_min,
            triggered_by=triggered_by,
            started_notification=note,
        )
    except RunnerBusy as e:
        logger.info("Deferred zone '%s': %s", zone_id, e)
        return "busy"
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

    logger.info("Accepted zone '%s' via %s (%.0f min)", zone_id, triggered_by, duration_min)
    return "started"


async def _run_cron_sequence_job(
    sequence_id: str,
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
) -> str:
    """Run a cron occurrence, durably deferring it while safety work is active."""
    result = await run_sequence_job(
        sequence_id,
        runner,
        ha,
        config,
        session_factory,
        triggered_by="cron",
    )
    if result == "busy":
        now = datetime.now(UTC).replace(tzinfo=None)
        with session_factory() as session:
            deferred = session.get(DeferredCronRun, sequence_id)
            if deferred is None:
                session.add(
                    DeferredCronRun(
                        sequence_id=sequence_id,
                        created_at=now,
                        expires_at=now + _DEFERRED_CRON_TTL,
                    )
                )
                session.commit()
            elif deferred.expires_at <= now:
                deferred.created_at = now
                deferred.expires_at = now + _DEFERRED_CRON_TTL
                session.add(deferred)
                session.commit()
        logger.info("Deferred cron occurrence for '%s'", sequence_id)
    return result


async def _retry_deferred_cron_runs(
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
) -> None:
    """Retry short-lived cron occurrences once valve safety work has finished."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_factory() as session:
        deferred = list(session.exec(select(DeferredCronRun)).all())

    for row in deferred:
        if row.expires_at <= now:
            logger.warning("Dropping expired deferred cron occurrence for '%s'", row.sequence_id)
            result = "expired"
            _log_decision(session_factory, row.sequence_id, "cron", "skipped", "expired")
            # A scheduled run is being silently lost — tell the user, since safety
            # work (HA outage / valve cleanup at boot) blocked it past its TTL.
            seq_cfg = config.sequences.get(row.sequence_id)
            if seq_cfg is not None:
                note = t("skip.expired", config.language, label=seq_cfg.label)
                await push_notification(ha, config, note, category="skip")
                await broadcast_notification(note, level="warning")
        else:
            result = await run_sequence_job(
                row.sequence_id,
                runner,
                ha,
                config,
                session_factory,
                triggered_by="cron",
                consume_skip=False,
            )
        if result in {"busy", "conflict"}:
            continue
        with session_factory() as session:
            current = session.get(DeferredCronRun, row.sequence_id)
            if current is not None:
                session.delete(current)
                session.commit()


async def _plan_tick(
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
    session_factory: SessionFactory,
) -> None:
    now = datetime.now(UTC)

    # Safety net: retry closing any valve whose turn_off was never confirmed (so a
    # failed close is durably retried rather than relying on a future HA reconnect).
    try:
        await runner.retry_pending_closes()
    except Exception:
        logger.exception("retry_pending_closes failed")

    await _retry_deferred_cron_runs(runner, ha, config, session_factory)

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
            result = await run_sequence_job(
                plan.sequence_id,
                runner,
                ha,
                config,
                session_factory,
                triggered_by="plan",
                override_min=override_min,
            )

        # Keep the plan on a transient busy/conflict so the next tick retries it;
        # drop it once it has started or was deterministically skipped.
        if result in {"busy", "conflict"}:
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


class WindAbortMonitor:
    """Aborts running wind-blocked sequences only after a *sustained* wind alarm.

    Wind blocking at start is handled by the run gates; this covers wind that
    begins mid-run. A brief gust must not abort the watering, so each affected
    run is aborted only if the alarm is still active after its threshold:
    ``min(config.wind.abort_after_min, 10% of the run's planned duration)`` —
    short runs react proportionally faster. The alarm clearing before the
    threshold cancels every pending abort.

    Only real sequences with ``wind_blocks`` are affected; standalone zone runs
    have no wind blocking. A run resumed by crash recovery while the alarm is
    already active is picked up on the next wind transition (edge case).
    """

    def __init__(self, runner: SequenceRunner, config: AppConfig, ha: HAClient) -> None:
        self._runner = runner
        self._config = config
        self._ha = ha
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def on_wind_state(self, is_on: bool) -> None:
        if not is_on:
            for task in self._tasks.values():
                task.cancel()
            self._tasks.clear()
            return
        for status in self._runner.iter_runs():
            run_id = status.sequence_id
            if run_id is None or run_id in self._tasks:
                continue
            seq = self._config.sequences.get(run_id)
            if seq is None or not seq.wind_blocks:
                continue
            delay_s = self._threshold_min(status, seq) * 60.0
            task = asyncio.create_task(
                self._abort_after(run_id, delay_s), name=f"wind-abort-{run_id}"
            )
            self._tasks[run_id] = task

            def _cleanup(t: asyncio.Task[None], rid: str = run_id) -> None:
                self._discard(rid, t)

            task.add_done_callback(_cleanup)

    def _discard(self, run_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is task:
            self._tasks.pop(run_id, None)

    def _threshold_min(self, status: SequenceStatus, seq: SequenceConfig) -> float:
        configured = self._config.wind.abort_after_min
        if status.current_zone is None:
            return configured
        # Planned total ≈ current per-zone duration × zone count (good enough for
        # a reaction threshold; resumed first zones make it slightly conservative).
        planned_total = status.current_zone.duration_min * max(1, len(seq.zones))
        return min(configured, 0.1 * planned_total)

    async def _abort_after(self, run_id: str, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        # Re-check live conditions: the run may have ended on its own, and a
        # missed "off" event must not abort a run after the alarm cleared.
        if self._ha.get_state_value(self._config.sensors.wind) != "on":
            return
        if run_id not in self._runner.running_run_ids():
            return
        label = _run_label(self._config, run_id)
        logger.info("Sustained wind alarm — aborting '%s'", run_id)
        try:
            await self._runner.stop(run_id, reason="wind")
        except Exception:
            logger.exception("Error aborting run '%s' on wind", run_id)
            return
        note = t("abort.wind", self._config.language, label=label)
        await push_notification(self._ha, self._config, note, category="abort")
        await broadcast_sequence_changed(run_id, "idle", "wind")
        await broadcast_notification(note, level="warning")


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
    if not any("reminder" in target.categories for target in config.ha.notify_targets):
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
    if not any("reminder" in target.categories for target in config.ha.notify_targets):
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
                _run_cron_sequence_job,
                trigger=trigger,
                args=[seq_id, runner, ha, config, session_factory],
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
    on_weather_metrics_refreshed: Callable[[], Any] | None = None,
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

    async def _refresh_rain_forecast_and_publish() -> None:
        await refresh_rain_forecast_max(config, ha, session_factory)
        if on_weather_metrics_refreshed is None:
            return
        result = on_weather_metrics_refreshed()
        if result is not None:
            await result

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

    # Track the day's peak precipitation forecast so a late downward revision can't
    # restart irrigation that an earlier, higher forecast had stopped. The recorder
    # retains the full day's history, so an hourly poll still captures any peak; the
    # initial fetch is triggered from the HA-connected callback (see main).
    scheduler.add_job(
        _refresh_rain_forecast_and_publish,
        trigger=IntervalTrigger(hours=1),
        id="rain-forecast-max",
        name="Rain forecast max refresh",
        max_instances=1,
        misfire_grace_time=600,
    )

    async def _rain_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        await _on_rain(entity_id, new_state, runner, config, ha)
        # On any rain-sensor transition (on or off), recompute the rain-confirmed peak
        # promptly so suppression reflects a just-started/-ended rain before the next
        # hourly refresh (best-effort; the recompute swallows fetch errors).
        if entity_id == config.sensors.rain:
            await refresh_rain_confirmed_peak(config, ha)
            await refresh_recent_rain_credit(config, ha, session_factory)
            await refresh_et0_balance(config, ha, session_factory)
            if on_weather_metrics_refreshed is not None:
                result = on_weather_metrics_refreshed()
                if result is not None:
                    await result

    ha.subscribe_state_changes(_rain_cb)
    logger.info("Rain listener registered: '%s'", config.sensors.rain)

    # Sustained wind aborts running wind-blocked sequences (a gust does not).
    wind_monitor = WindAbortMonitor(runner, config, ha)

    async def _wind_cb(entity_id: str, new_state: dict[str, Any]) -> None:
        if entity_id != config.sensors.wind:
            return
        state = new_state.get("state")
        if state in ("on", "off"):
            await wind_monitor.on_wind_state(state == "on")

    ha.subscribe_state_changes(_wind_cb)
    logger.info("Wind listener registered: '%s'", config.sensors.wind)

    return scheduler
