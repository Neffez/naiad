import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import SimpleNamespace
from typing import Any

from naiad.config import (
    STAIRCASE_RETRY_ON_FAILURE_S,
    AppConfig,
    ScheduleConfig,
    SequenceConfig,
    ZoneConfig,
    staircase_retrigger_interval_min,
)
from naiad.domain.models import ActiveRun, RunHistory
from naiad.domain.resume import (
    clear_active_run,
    clear_all_snapshots,
    clear_pending_close,
    clear_snapshot,
    load_active_runs,
    load_pending_closes,
    load_snapshot,
    save_active_run,
    save_pause_snapshot,
    save_pending_close,
)
from naiad.drivers.protocol import IValveDriver
from naiad.i18n import t as translate

logger = logging.getLogger(__name__)


class MutexConflict(Exception):
    """A run could not start because of a conflict with an active run."""


class RunnerBusy(MutexConflict):
    """A run could not start while the runner is performing safety work."""


class InitialRecoveryInProgress(RunnerBusy):
    """A run could not start before the first HA-backed recovery completed."""


class ValveCleanupInProgress(RunnerBusy):
    """A run could not start while safety cleanup is issuing valve closes."""


class ZoneBusy(MutexConflict):
    """One or more requested zones are already in use by an active run.

    Subclasses :class:`MutexConflict` so existing ``except MutexConflict`` paths
    keep handling it. ``zones`` holds the conflicting zone ids.
    """

    def __init__(self, zones: list[str]) -> None:
        self.zones = zones
        super().__init__(f"zone(s) already running: {', '.join(zones)}")


class SequenceNotFound(Exception):
    """Sequence ID does not exist in config."""


class ZoneNotFound(Exception):
    """Zone ID does not exist in config."""


# A standalone single-zone run reuses the whole sequence machinery (history,
# watchdog, valve safety, crash-safe valve close) by executing under a synthetic
# sequence id derived from the zone id. The prefix is deliberately unlikely to
# collide with a real (YAML-defined) sequence id.
ZONE_RUN_PREFIX = "__zone__"


def zone_run_id(zone_id: str) -> str:
    """The synthetic sequence id a standalone single-zone run executes under."""
    return f"{ZONE_RUN_PREFIX}{zone_id}"


def zone_id_of_run(run_id: str) -> str | None:
    """Return the zone id of a single-zone run id, or None for a real sequence."""
    if run_id.startswith(ZONE_RUN_PREFIX):
        return run_id[len(ZONE_RUN_PREFIX) :]
    return None


def build_zone_sequence(zone_id: str, zone_cfg: ZoneConfig, duration_min: float) -> SequenceConfig:
    """A throwaway single-zone sequence used to run one zone in isolation.

    The duration is applied verbatim (passed as the run's override), so the
    factor/range logic is bypassed. The watchdog stays safely above the run
    duration since it bounds this one zone.
    """
    watchdog = max(int(math.ceil(duration_min)) + 10, 1)
    return SequenceConfig(
        label=zone_cfg.label,
        zones=[zone_id],
        basis_min_per_zone=duration_min,
        watchdog_min=watchdog,
        schedule=ScheduleConfig(),
    )


class NotRunning(Exception):
    """No sequence is currently running."""


class SequenceState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    # NOTE: PAUSED is never returned by SequenceRunner.status_of() — on pause the run
    # task ends and the runner goes IDLE. "Paused" is derived at the API layer from
    # the persisted ResumeSnapshot (see api/sequences.py:_sequence_status).
    PAUSED = "paused"


@dataclass
class ZoneProgress:
    zone_id: str
    started_at: datetime
    duration_min: float


@dataclass
class SequenceStatus:
    state: SequenceState
    sequence_id: str | None = None
    current_zone: ZoneProgress | None = None
    triggered_by: str = "manual"


@dataclass
class _Run:
    """In-memory state of one active run (a real sequence or a standalone zone).

    For a standalone single-zone run, ``seq`` is the synthetic single-zone
    config and ``run_id`` is the synthetic ``__zone__<id>`` id.
    """

    run_id: str
    seq: SequenceConfig
    triggered_by: str
    stop_event: asyncio.Event
    pause_event: asyncio.Event
    is_zone_run: bool = False
    started_notification: str | None = None
    stop_reason: str = "manual_stop"
    current_zone: ZoneProgress | None = None
    task: asyncio.Task[None] | None = None


_STOP = "stop"
_PAUSE = "pause"
_DONE = "done"
_WATCHDOG = "watchdog"
_RETRIGGER_FAILED = "retrigger_failed"


async def _staircase_retrigger_loop(
    retrigger: Callable[[], Awaitable[None]],
    interval_s: float,
    window_s: float,
    error_event: asyncio.Event,
) -> None:
    """Re-send "on" to a staircase actuator before its timer elapses.

    The actuator closes the valve on its own ``window_s`` after the last
    successful "on", so the loop tracks a deadline = last success + window and
    re-triggers ahead of it. A failed trigger (HA hiccup) is retried sooner than
    the normal interval — a slightly late trigger is harmless since Naiad turns
    the valve off at the end anyway. If no "on" lands before the deadline, the
    actuator has physically closed the valve: signal ``error_event`` so the run
    ends early (and the user is notified) rather than silently watering short.

    This task lives only for the duration of one zone's wait and is always
    cancelled when that wait returns (including on the software watchdog), so it
    can never keep re-triggering past the watering window and defeat the
    actuator's hardware safety net.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window_s
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            error_event.set()
            return
        await asyncio.sleep(min(interval_s, remaining))
        try:
            await retrigger()
            deadline = loop.time() + window_s
            logger.debug("staircase re-trigger sent")
        except Exception:
            logger.warning(
                "staircase re-trigger failed — retrying before actuator timeout",
                exc_info=True,
            )
            interval_s = STAIRCASE_RETRY_ON_FAILURE_S


async def _wait_zone(
    duration_min: float,
    watchdog_min: float,
    stop_event: asyncio.Event,
    pause_event: asyncio.Event,
    retrigger: Callable[[], Awaitable[None]] | None = None,
    retrigger_interval_min: float | None = None,
    staircase_window_min: float | None = None,
) -> str:
    zone_task = asyncio.ensure_future(asyncio.sleep(duration_min * 60))
    watchdog_task = asyncio.ensure_future(asyncio.sleep(watchdog_min * 60))
    stop_task = asyncio.ensure_future(stop_event.wait())
    pause_task = asyncio.ensure_future(pause_event.wait())

    # Optional staircase re-trigger: a background task that keeps the actuator's
    # hardware timer alive, plus an error event it raises if it can no longer do
    # so before the actuator auto-closes the valve.
    error_event = asyncio.Event()
    retrigger_task: asyncio.Task[None] | None = None
    if (
        retrigger is not None
        and retrigger_interval_min is not None
        and staircase_window_min is not None
    ):
        retrigger_task = asyncio.ensure_future(
            _staircase_retrigger_loop(
                retrigger,
                retrigger_interval_min * 60,
                staircase_window_min * 60,
                error_event,
            )
        )
    error_task = asyncio.ensure_future(error_event.wait())

    try:
        done, pending = await asyncio.wait(
            [zone_task, watchdog_task, stop_task, pause_task, error_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in (zone_task, watchdog_task, stop_task, pause_task, error_task):
            t.cancel()
        # The re-trigger task must be dead before the caller turns the valve off,
        # so a stray "on" can never follow the closing "off".
        if retrigger_task is not None:
            retrigger_task.cancel()
            with suppress(asyncio.CancelledError):
                await retrigger_task

    if stop_task in done:
        return _STOP
    if pause_task in done:
        return _PAUSE
    if watchdog_task in done:
        return _WATCHDOG
    if error_task in done:
        return _RETRIGGER_FAILED
    return _DONE


class SequenceRunner:
    def __init__(
        self,
        config: AppConfig,
        driver: IValveDriver,
        session_factory: Callable[[], Any],
    ) -> None:
        self._config = config
        self._driver = driver
        self._session_factory = session_factory
        # All active runs (real sequences and standalone single-zone runs), keyed
        # by run id. Multiple runs may execute in parallel as long as their zone
        # sets are disjoint (enforced at start by _check_zone_conflict).
        self._runs: dict[str, _Run] = {}
        # Set once initial crash recovery has run. retry_pending_closes() is a no-op
        # until then, so the periodic close retry can never close a valve that
        # recovery would have resumed.
        self._recovery_complete = False
        # Production enables this before accepting scheduler/API starts. Kept
        # separate from _recovery_complete so isolated runner users can opt in.
        self._starts_blocked_for_recovery = False
        # Reconciliation issues physical close commands across awaits. Starts are
        # rejected while it runs so a newly-opened valve cannot race a stale close.
        self._cleanup_in_progress = False
        self._cleanup_lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Invoked once a run actually opens its first valve (sequence_id, triggered_by),
        # so "running" is broadcast only after the run is confirmed, not when it's scheduled.
        self.on_started: Callable[[str, str, str | None], Awaitable[None]] | None = None
        # Invoked for noteworthy run events that warrant a notification
        # (message, level), e.g. a watchdog abort. Wired to push/broadcast in main.
        self.on_notification: Callable[[str, str], Awaitable[None]] | None = None
        # Invoked after a zone's history row is finalized, so external consumers
        # (e.g. the MQTT statistics bridge) can refresh the published totals.
        self.on_run_recorded: Callable[[], Awaitable[None]] | None = None

    async def _emit_notification(self, message: str, level: str) -> None:
        if self.on_notification is None:
            return
        try:
            await self.on_notification(message, level)
        except Exception:
            logger.exception("on_notification callback failed")

    def _spawn_background(self, coro: Coroutine[Any, Any, None], *, name: str) -> None:
        """Run best-effort callbacks without delaying valve safety timers."""
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _emit_started(
        self,
        sequence_id: str,
        triggered_by: str,
        notification: str | None,
    ) -> None:
        if self.on_started is None:
            return
        try:
            await asyncio.wait_for(
                self.on_started(sequence_id, triggered_by, notification),
                timeout=5.0,
            )
        except TimeoutError:
            logger.warning("on_started callback timed out for '%s'", sequence_id)
        except Exception:
            logger.exception("on_started callback failed for '%s'", sequence_id)

    async def _emit_run_recorded(self) -> None:
        if self.on_run_recorded is None:
            return
        try:
            await self.on_run_recorded()
        except Exception:
            logger.exception("on_run_recorded callback failed")

    def _seq(self, run_id: str) -> SequenceConfig | None:
        """Resolve a sequence config by id, including an active single-zone run's
        synthetic config."""
        seq = self._config.sequences.get(run_id)
        if seq is not None:
            return seq
        run = self._runs.get(run_id)
        return run.seq if run is not None else None

    def _switches_in_use(self, exclude_run: str | None = None) -> set[str]:
        """Every switch entity reserved by an active run.

        Ownership is tracked by physical switch (not zone id): two runs may not
        drive the same valve, and the periodic close-retry must never touch a switch
        a live run legitimately holds open. Zones are mapped to switches via the
        live config; reload is blocked while any run is active, so this is stable.
        """
        used: set[str] = set()
        for run_id, run in self._runs.items():
            if run_id == exclude_run:
                continue
            for zone_id in run.seq.zones:
                zone_cfg = self._config.zones.get(zone_id)
                if zone_cfg is not None:
                    used.add(zone_cfg.switch)
        return used

    def _pending_close_switches(self) -> set[str]:
        """Switch entities with an unconfirmed-open valve (a pending close).

        Reserved like a live run's switches: a new run must not open a valve whose
        previous close was never confirmed, otherwise the periodic retry could close
        the new run's valve out from under it.
        """
        with self._session_factory() as session:
            return {rec.switch for rec in load_pending_closes(session)}

    def _active_run_switches(self) -> set[str]:
        """Switch entities retained by crash-recovery records.

        An unhandled runner error can remove the in-memory run while leaving its
        valve open. Reserve the persisted physical switch until retry confirms it
        is closed, so a fresh run can never be opened underneath that retry.
        """
        with self._session_factory() as session:
            return {rec.switch for rec in load_active_runs(session) if rec.switch}

    def _check_zone_conflict(self, zones: list[str]) -> None:
        reserved = (
            self._switches_in_use() | self._pending_close_switches() | self._active_run_switches()
        )
        conflict = sorted(
            zone_id
            for zone_id in zones
            if (zc := self._config.zones.get(zone_id)) is not None and zc.switch in reserved
        )
        if conflict:
            raise ZoneBusy(conflict)

    def is_managed(self, zone_id: str) -> bool:
        return any(zone_id in run.seq.zones for run in self._runs.values())

    def is_switch_managed(self, switch: str) -> bool:
        """True if any live run owns ``switch`` (used to protect it from the retry)."""
        return switch in self._switches_in_use()

    def conflicting_run(self, zones: list[str]) -> str | None:
        """The run id that reserves any of ``zones`` (or None)."""
        wanted = set(zones)
        for run_id, run in self._runs.items():
            if wanted & set(run.seq.zones):
                return run_id
        return None

    def _status_of_run(self, run: _Run) -> SequenceStatus:
        return SequenceStatus(
            state=SequenceState.RUNNING,
            sequence_id=run.run_id,
            current_zone=run.current_zone,
            triggered_by=run.triggered_by,
        )

    def status_of(self, run_id: str) -> SequenceStatus:
        """Live in-memory state of one run: RUNNING if active, else IDLE.

        A paused run reads as IDLE here; the PAUSED state is reconstructed from
        the ResumeSnapshot at the API layer."""
        run = self._runs.get(run_id)
        if run is None:
            return SequenceStatus(state=SequenceState.IDLE)
        return self._status_of_run(run)

    def iter_runs(self) -> list[SequenceStatus]:
        """A status for every currently-active run."""
        return [self._status_of_run(run) for run in self._runs.values()]

    def running_run_ids(self) -> list[str]:
        return list(self._runs.keys())

    def any_running(self) -> bool:
        return bool(self._runs)

    def can_reload_config(self) -> bool:
        """Whether the shared zone-to-switch mapping can be mutated safely.

        Deliberately *not* gated on ``_starts_blocked_for_recovery``: the pre-recovery
        window can last indefinitely while HA is unreachable, and blocking reload on it
        would lock the user out of fixing configuration exactly when HA is down at boot.
        Recovery itself is robust to a reload — it closes by the stored physical switch
        and resolves reconfigured switches per-record — and its execution is already
        covered here: resumed runs register into ``self._runs`` synchronously before any
        await, and ``reconcile_valves``/``retry_pending_closes`` set ``_cleanup_in_progress``
        while they issue closes. Fresh starts stay blocked via ``_ensure_start_allowed``.
        """
        return not self._runs and not self._cleanup_in_progress

    def require_initial_recovery(self) -> None:
        """Reject fresh starts until the first HA-backed recovery succeeds."""
        self._recovery_complete = False
        self._starts_blocked_for_recovery = True

    def _ensure_start_allowed(self) -> None:
        if self._starts_blocked_for_recovery:
            raise InitialRecoveryInProgress("initial valve recovery is still in progress")
        if self._cleanup_in_progress:
            raise ValveCleanupInProgress("valve safety cleanup is in progress")

    def find_zone_run(self, zone_id: str) -> tuple[str, ZoneProgress] | None:
        """The (run_id, ZoneProgress) of the run that currently has ``zone_id``
        open, or None."""
        for run_id, run in self._runs.items():
            if run.current_zone is not None and run.current_zone.zone_id == zone_id:
                return run_id, run.current_zone
        return None

    async def start(
        self,
        sequence_id: str,
        factor_pct: float = 100.0,
        override_min: float | None = None,
        triggered_by: str = "manual",
        started_notification: str | None = None,
    ) -> None:
        self._ensure_start_allowed()
        if sequence_id not in self._config.sequences:
            raise SequenceNotFound(sequence_id)
        if sequence_id in self._runs:
            raise MutexConflict(f"'{sequence_id}' is already running")
        self._check_zone_conflict(self._config.sequences[sequence_id].zones)

        run = _Run(
            run_id=sequence_id,
            seq=self._config.sequences[sequence_id],
            triggered_by=triggered_by,
            stop_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            started_notification=started_notification,
        )
        self._runs[sequence_id] = run  # registered before first await — asyncio mutex
        run.task = asyncio.create_task(
            self._execute(run, factor_pct, override_min),
            name=f"seq-{sequence_id}",
        )

    async def start_zone(
        self,
        zone_id: str,
        duration_min: float,
        triggered_by: str = "manual",
        started_notification: str | None = None,
    ) -> None:
        """Run a single zone in isolation for ``duration_min`` minutes.

        Runs in parallel with other runs as long as the zone is free (it must not
        already be reserved by a running sequence or another zone run), reusing
        the full execution path via a synthetic single-zone sequence.
        """
        self._ensure_start_allowed()
        if zone_id not in self._config.zones:
            raise ZoneNotFound(zone_id)
        run_id = zone_run_id(zone_id)
        if run_id in self._runs:
            raise MutexConflict(f"zone '{zone_id}' is already running")
        self._check_zone_conflict([zone_id])

        run = _Run(
            run_id=run_id,
            seq=build_zone_sequence(zone_id, self._config.zones[zone_id], duration_min),
            triggered_by=triggered_by,
            stop_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            is_zone_run=True,
            started_notification=started_notification,
        )
        self._runs[run_id] = run  # registered before first await — asyncio mutex
        run.task = asyncio.create_task(
            self._execute_zone(run, duration_min),
            name=f"zone-{zone_id}",
        )

    async def _execute_zone(self, run: _Run, duration_min: float) -> None:
        try:
            # A standalone zone run deliberately bypasses the resume/snapshot
            # machinery (which is keyed to real sequences): it always runs its one
            # zone fresh for the given duration.
            await self._run_zones(
                run,
                factor_pct=100.0,
                start_index=0,
                start_remaining=None,
                override_min=duration_min,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep the ActiveRun record: the valve may still be open and the
            # record is what lets retry_pending_closes (and boot recovery) close it.
            logger.exception(
                "Unhandled error in zone run '%s' — valve close will be retried", run.run_id
            )
        finally:
            self._runs.pop(run.run_id, None)

    async def stop(self, run_id: str, reason: str = "manual_stop") -> None:
        run = self._runs.get(run_id)
        if run is None:
            raise NotRunning
        run.stop_reason = reason
        with self._session_factory() as session:
            clear_snapshot(session, run_id)
        run.stop_event.set()
        if run.task:
            await run.task

    async def pause(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            raise NotRunning
        run.pause_event.set()
        if run.task:
            await run.task

    def discard_snapshot(self, sequence_id: str) -> None:
        """Drop a paused sequence's resume snapshot (cancel without resuming)."""
        with self._session_factory() as session:
            clear_snapshot(session, sequence_id)

    def clear_paused_snapshots(self) -> list[str]:
        """Discard every persisted paused-run snapshot, returning their sequence ids.

        Used to cancel paused runs on rain so they can't later be resumed; returns
        an empty list if nothing was paused.
        """
        with self._session_factory() as session:
            return clear_all_snapshots(session)

    async def _execute(
        self,
        run: _Run,
        factor_pct: float,
        override_min: float | None = None,
    ) -> None:
        sequence_id = run.run_id
        try:
            with self._session_factory() as session:
                snapshot = load_snapshot(session, sequence_id)

            start_index = 0
            start_remaining: float | None = None
            if snapshot is not None:
                start_index = snapshot.zone_index
                start_remaining = snapshot.remaining_min
                run.triggered_by = "resume"
                with self._session_factory() as session:
                    clear_snapshot(session, sequence_id)

            await self._run_zones(
                run,
                factor_pct,
                start_index,
                start_remaining,
                override_min,
            )
        except asyncio.CancelledError:
            # Process shutdown/restart — keep the ActiveRun record so the run can
            # be recovered on the next boot. Re-raise without clearing it.
            raise
        except Exception:
            # Keep the ActiveRun record: the valve may still be open and the
            # record is what lets retry_pending_closes (and boot recovery) close it.
            logger.exception(
                "Unhandled error in sequence '%s' — valve close will be retried", sequence_id
            )
        finally:
            self._runs.pop(sequence_id, None)

    def _effective_seq_params(self, seq: SequenceConfig, sequence_id: str) -> tuple[float, float]:
        """Return (basis_min_per_zone, watchdog_min) with DB overrides applied."""
        from naiad.domain.models import SequenceOverride

        basis = float(seq.basis_min_per_zone)
        watchdog = float(seq.watchdog_min)

        with self._session_factory() as session:
            override = session.get(SequenceOverride, sequence_id)
            if override is not None:
                if override.basis_min_per_zone is not None:
                    basis = float(override.basis_min_per_zone)
                if override.watchdog_min is not None:
                    watchdog = float(override.watchdog_min)

        return basis, watchdog

    async def _safe_turn_off(
        self, zone_cfg: Any, zone_id: str | None = None, attempts: int = 3, backoff_s: float = 1.0
    ) -> bool:
        """Turn a valve off, retrying on failure. Never raises.

        A failing turn_off (e.g. HA disconnected) must not abort the run loop
        before history is recorded, and must not leave the loop in a state where
        the valve is silently assumed off. Returns True if HA confirmed the
        command, False if the valve may still be physically open. Pending-close
        bookkeeping is keyed by the switch entity (``zone_cfg.switch``), so it
        survives zone renames/removals and never collides with another switch.
        """
        switch = zone_cfg.switch
        for attempt in range(1, attempts + 1):
            try:
                await self._driver.turn_off(zone_cfg)
                # Confirmed off — drop the pending-close record for exactly this switch.
                with self._session_factory() as session:
                    clear_pending_close(session, switch)
                return True
            except Exception:
                logger.warning(
                    "turn_off failed for switch %s (attempt %d/%d)",
                    switch,
                    attempt,
                    attempts,
                    exc_info=True,
                )
                if attempt < attempts:
                    await asyncio.sleep(backoff_s)
        logger.error(
            "Could not turn off switch %s after %d attempts — valve may still be open; "
            "it will be retried by retry_pending_closes (and reconciliation once HA "
            "is reachable)",
            switch,
            attempts,
        )
        # Durably record the open valve per-switch so it is never lost — even when a
        # later zone overwrites this sequence's ActiveRun, no run owns the zone
        # (reconciliation failure), or a reload later changes the zone's config.
        with self._session_factory() as session:
            save_pending_close(session, switch, zone_id)
        return False

    async def reconcile_valves(self, exclude: set[str] | str | None = None) -> None:
        """Turn off every configured zone except the live/excluded ones.

        Safety net for valves left ON by a previous process / crash, and for
        closing a zone after an HA disconnect aborted its run. ``exclude`` keeps
        specific zones open (used when resuming runs that own those zones); all
        switches reserved by currently-live runs are kept open implicitly.
        Idempotent: turning off an already-off switch is harmless.
        """
        if exclude is None:
            excluded: set[str] = set()
        elif isinstance(exclude, str):
            excluded = {exclude}
        else:
            excluded = set(exclude)
        async with self._cleanup_lock:
            self._cleanup_in_progress = True
            try:
                for zone_id, zone_cfg in self._config.zones.items():
                    if zone_id in excluded or self.is_switch_managed(zone_cfg.switch):
                        continue
                    await self._safe_turn_off(zone_cfg, zone_id, attempts=1)
            finally:
                self._cleanup_in_progress = False

    def _clear_active_run(self, sequence_id: str) -> None:
        with self._session_factory() as session:
            clear_active_run(session, sequence_id)

    def _retain_active_switch_for_close(
        self, record: ActiveRun, zone_id: str | None = None
    ) -> None:
        """Preserve an ActiveRun's physical switch before discarding the run."""
        with self._session_factory() as session:
            if record.switch is not None:
                save_pending_close(session, record.switch, zone_id)
            clear_active_run(session, record.sequence_id)

    async def recover_runs(self) -> list[str]:
        """Recover (or clean up) in-flight runs after a crash/restart.

        Called once when HA first becomes reachable. Policy ("zone duration as
        the bound") is applied per persisted run: if the current zone's planned
        window has **not** elapsed, resume it for the remaining time and continue
        the following zones; otherwise the run is stale → discard it. After all
        runs are processed, orphaned valves (not owned by a resumed run) are
        closed. Returns the per-run actions taken (for logging/tests).
        """
        with self._session_factory() as session:
            records = load_active_runs(session)

        if not records:
            await self.reconcile_valves()
            self._recovery_complete = True
            self._starts_blocked_for_recovery = False
            return ["reconciled"]

        actions: list[str] = []
        resuming_zones: set[str] = set()
        for record in records:
            action, zone = self._recover_one(record)
            actions.append(action)
            if zone is not None:
                resuming_zones.add(zone)

        # Close any valve not owned by a resumed run (runs registered above keep
        # their zones open via reconcile_valves' implicit running-zone exclusion).
        await self.reconcile_valves(exclude=resuming_zones)
        self._recovery_complete = True
        self._starts_blocked_for_recovery = False
        return actions

    async def retry_pending_closes(self) -> None:
        """Durably close valves whose turn_off was never confirmed.

        Two record kinds drive this: per-switch :class:`PendingClose` rows (written
        by ``_safe_turn_off`` on any unconfirmed close — including intermediate
        zones of a multi-zone run and reconciliation failures) and per-sequence
        ``ActiveRun`` rows left by a hard crash or an unhandled error.
        Called periodically (the plan tick), it retries until success instead of
        relying on a future HA reconnect, and works even while other runs are
        active (where reconnect reconciliation would be skipped).

        A switch currently owned by a live run is never touched
        (``is_switch_managed``), so the retry can never close a valve that a running
        sequence legitimately keeps open. No-op until initial crash recovery has
        run, so it can never close a valve that recovery would otherwise resume.
        """
        if not self._recovery_complete:
            return

        async with self._cleanup_lock:
            self._cleanup_in_progress = True
            try:
                await self._retry_pending_closes_locked()
            finally:
                self._cleanup_in_progress = False

    async def _retry_pending_closes_locked(self) -> None:
        """Retry durable closes while fresh starts and config reloads are blocked."""
        # Per-switch pending closes: the authoritative, non-overwritable record of an
        # open valve. The stored switch entity is closed directly (never re-resolved
        # against the live config, which a reload may have changed), so the exact
        # valve that was left open is the one we close. _safe_turn_off clears the
        # row itself on a confirmed close.
        with self._session_factory() as session:
            pending = load_pending_closes(session)
        for rec in pending:
            if self.is_switch_managed(rec.switch):
                continue  # a live run owns this switch — its valve is legitimately open
            logger.warning(
                "Retrying close of switch %s (zone %s; turn_off was unconfirmed)",
                rec.switch,
                rec.zone_id,
            )
            target = SimpleNamespace(switch=rec.switch)
            await self._safe_turn_off(target, rec.zone_id, attempts=1)

        # Per-sequence ActiveRun records: close the run's current zone and clear the
        # record once confirmed. Guarded by is_switch_managed so a different run that
        # now owns the same switch is never disturbed.
        with self._session_factory() as session:
            records = load_active_runs(session)
        for record in records:
            if record.sequence_id in self._runs:
                continue  # still live — its valve is legitimately open
            if record.switch is not None:
                zone_id: str | None = None
                seq = self._config.sequences.get(record.sequence_id)
                if seq is not None and 0 <= record.zone_index < len(seq.zones):
                    zone_id = seq.zones[record.zone_index]
                if self.is_switch_managed(record.switch):
                    continue
                logger.warning(
                    "Retrying close of switch %s from active run %s",
                    record.switch,
                    record.sequence_id,
                )
                target = SimpleNamespace(switch=record.switch)
                if await self._safe_turn_off(target, zone_id, attempts=1):
                    self._clear_active_run(record.sequence_id)
                continue

            # Legacy rows created before ActiveRun stored the physical switch.
            seq = self._config.sequences.get(record.sequence_id)
            if seq is not None and 0 <= record.zone_index < len(seq.zones):
                zone_id = seq.zones[record.zone_index]
            else:
                zone_id = zone_id_of_run(record.sequence_id)
            zone_cfg = self._config.zones.get(zone_id) if zone_id is not None else None
            if zone_id is None or zone_cfg is None:
                self._clear_active_run(record.sequence_id)  # unknown zone — nothing to close
                continue
            if self.is_switch_managed(zone_cfg.switch):
                continue  # another live run owns this switch now — do not close it
            logger.warning("Retrying close of zone %s (turn_off was unconfirmed)", zone_id)
            if await self._safe_turn_off(zone_cfg, zone_id, attempts=1):
                self._clear_active_run(record.sequence_id)

    def _recover_one(self, record: ActiveRun) -> tuple[str, str | None]:
        """Process one persisted run; returns (action, resuming_zone_or_None).

        Registers a live ``_Run`` and starts its recovery task when resuming.
        Does not close valves itself — the caller reconciles once at the end.
        """
        seq = self._config.sequences.get(record.sequence_id)
        if seq is None or not 0 <= record.zone_index < len(seq.zones):
            logger.warning(
                "Crash recovery: discarding active run for unknown sequence/zone '%s'",
                record.sequence_id,
            )
            self._retain_active_switch_for_close(record)
            return "discarded", None

        existing = self._runs.get(record.sequence_id)
        if existing is not None:
            zone_id = (
                existing.current_zone.zone_id
                if existing.current_zone is not None
                else seq.zones[record.zone_index]
            )
            return "already_resumed", zone_id

        resuming_zone = seq.zones[record.zone_index]
        zone_cfg = self._config.zones.get(resuming_zone)
        if record.switch is not None and (zone_cfg is None or zone_cfg.switch != record.switch):
            logger.warning(
                "Crash recovery: switch for '%s' changed from %s; closing the old switch "
                "instead of resuming",
                record.sequence_id,
                record.switch,
            )
            self._retain_active_switch_for_close(record, resuming_zone)
            return "discarded_reconfigured", None

        started = record.zone_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - started).total_seconds() / 60.0

        if elapsed >= record.zone_planned_min:
            logger.warning(
                "Crash recovery: run '%s' is stale (zone elapsed %.1f >= planned %.1f min) "
                "— closing valves and discarding",
                record.sequence_id,
                elapsed,
                record.zone_planned_min,
            )
            self._retain_active_switch_for_close(record, resuming_zone)
            return "closed_stale", None

        remaining = max(0.0, min(record.zone_planned_min, record.zone_planned_min - elapsed))
        logger.info(
            "Crash recovery: resuming '%s' at zone '%s' (#%d) for %.1f more min",
            record.sequence_id,
            resuming_zone,
            record.zone_index,
            remaining,
        )

        run = _Run(
            run_id=record.sequence_id,
            seq=seq,
            triggered_by="resume",
            stop_event=asyncio.Event(),
            pause_event=asyncio.Event(),
        )
        self._runs[record.sequence_id] = run  # claim the run before awaiting
        run.task = asyncio.create_task(
            self._recover_execute(run, record, remaining),
            name=f"seq-resume-{record.sequence_id}",
        )
        return "resumed", resuming_zone

    async def _recover_execute(self, run: _Run, record: ActiveRun, remaining_min: float) -> None:
        try:
            await self._run_zones(
                run,
                factor_pct=100.0,
                start_index=record.zone_index,
                start_remaining=remaining_min,
                override_min=record.run_duration_min,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep the ActiveRun record: the valve may still be open and the
            # record is what lets retry_pending_closes (and boot recovery) close it.
            logger.exception(
                "Unhandled error during crash recovery of '%s' — valve close will be retried",
                run.run_id,
            )
        finally:
            self._runs.pop(run.run_id, None)

    async def _run_zones(
        self,
        run: _Run,
        factor_pct: float,
        start_index: int,
        start_remaining: float | None,
        override_min: float | None = None,
    ) -> None:
        sequence_id = run.run_id
        seq = run.seq
        triggered_by = run.triggered_by
        effective_basis, effective_watchdog = self._effective_seq_params(seq, sequence_id)

        if override_min is not None:
            duration_min = override_min
        else:
            lo, hi = seq.range
            basis = effective_basis * factor_pct / 100.0
            duration_min = max(float(lo), min(float(hi), basis))

        announced = False
        for i, zone_id in enumerate(seq.zones):
            if i < start_index:
                continue

            zone_cfg = self._config.zones[zone_id]
            zone_duration = (
                start_remaining
                if (i == start_index and start_remaining is not None)
                else duration_min
            )
            start_remaining = None  # only applies to first resumed zone

            started_at = datetime.now(UTC)
            run.current_zone = ZoneProgress(
                zone_id=zone_id, started_at=started_at, duration_min=zone_duration
            )
            # Persist the in-flight state so a hard crash can recover (see ActiveRun).
            with self._session_factory() as session:
                save_active_run(
                    session,
                    sequence_id,
                    i,
                    started_at,
                    zone_duration,
                    duration_min,
                    triggered_by,
                    zone_cfg.switch,
                )
            # Record the run in history immediately at start (ended_at/duration/
            # liters filled in when the zone ends) so it shows up in the history
            # while still running, not only after completion.
            with self._session_factory() as session:
                history_row = RunHistory(
                    zone_id=zone_id,
                    sequence_id=sequence_id,
                    started_at=started_at,
                    triggered_by=triggered_by,
                )
                session.add(history_row)
                session.commit()
                session.refresh(history_row)
                history_id = history_row.id
            try:
                await self._driver.turn_on(zone_cfg)
            except Exception:
                # turn_on may have reached HA before failing, so the valve might be
                # open. Try to close it right away (don't wait for the next plan
                # tick); _safe_turn_off persists a per-switch pending close if that
                # also fails. Then finalize history as aborted and end the run
                # instead of leaving an unreserved, untracked valve.
                logger.exception(
                    "turn_on failed for switch %s — closing immediately and aborting run %s",
                    zone_cfg.switch,
                    sequence_id,
                )
                closed = await self._safe_turn_off(zone_cfg, zone_id)
                abort_reason: str | None = "start_failed" if closed else "close_failed"
                with self._session_factory() as session:
                    row = session.get(RunHistory, history_id) if history_id is not None else None
                    if row is not None:
                        row.ended_at = datetime.now(UTC)
                        row.duration_min = 0.0
                        row.liters = 0.0
                        row.aborted = True
                        row.abort_reason = abort_reason
                        session.add(row)
                        session.commit()
                self._clear_active_run(sequence_id)
                await self._emit_run_recorded()
                seq_label = seq.label or sequence_id
                await self._emit_notification(
                    translate(
                        f"abort.{abort_reason}",
                        self._config.language,
                        label=seq_label,
                        zone=zone_cfg.label,
                    ),
                    "warning",
                )
                return
            logger.info("zone %s ON  (%.1f min)", zone_id, zone_duration)

            if not announced and self.on_started is not None:
                announced = True
                self._spawn_background(
                    self._emit_started(sequence_id, triggered_by, run.started_notification),
                    name=f"run-started-{sequence_id}",
                )

            # For a staircase-timer zone, keep the actuator's hardware timer alive
            # by re-sending "on" ahead of its expiry (see _staircase_retrigger_loop).
            # The task is bounded by _wait_zone, so capturing the loop's zone_cfg is
            # safe — it's cancelled before the next iteration reassigns it.
            retrigger_interval = staircase_retrigger_interval_min(zone_cfg)
            retrigger_cb: Callable[[], Awaitable[None]] | None = None
            if retrigger_interval is not None:

                async def _retrigger(zc: ZoneConfig = zone_cfg) -> None:
                    await self._driver.turn_on(zc)

                retrigger_cb = _retrigger
            result = await _wait_zone(
                zone_duration,
                effective_watchdog,
                run.stop_event,
                run.pause_event,
                retrigger=retrigger_cb,
                retrigger_interval_min=retrigger_interval,
                staircase_window_min=(
                    zone_cfg.staircase_min if retrigger_interval is not None else None
                ),
            )

            off_time = datetime.now(UTC)
            closed = await self._safe_turn_off(zone_cfg, zone_id)
            logger.info("zone %s OFF result=%s closed=%s", zone_id, result, closed)

            # This execution path ended deliberately, so it must never be resumed
            # after a restart. If the close was not confirmed, _safe_turn_off has
            # already written a switch-specific PendingClose for durable retry.
            def _release(sequence_id: str = sequence_id) -> None:
                self._clear_active_run(sequence_id)

            actual_min = (off_time - started_at).total_seconds() / 60.0
            liters = actual_min / 60.0 * zone_cfg.flow_lph
            # An unconfirmed close ends the run too (see the `if not closed` branch
            # below), so the history row must reflect the abort — otherwise it would
            # read as a successful run while a notification says the opposite.
            aborted = result in (_STOP, _WATCHDOG, _RETRIGGER_FAILED) or not closed

            # An unconfirmed close is the safety-critical outcome (a valve may be
            # physically open), so it takes precedence over the reason the zone
            # *ended* — the user must see "valve may be open", not just "watchdog".
            abort_reason = None
            if not closed:
                abort_reason = "close_failed"
            elif result == _WATCHDOG:
                abort_reason = "watchdog"
            elif result == _RETRIGGER_FAILED:
                abort_reason = "staircase_retrigger_failed"
            elif result == _STOP:
                abort_reason = run.stop_reason

            # Finalize the history row created at zone start.
            with self._session_factory() as session:
                row = session.get(RunHistory, history_id) if history_id is not None else None
                if row is not None:
                    row.ended_at = off_time
                    row.duration_min = actual_min
                    row.liters = liters
                    row.aborted = aborted
                    row.abort_reason = abort_reason
                    session.add(row)
                else:
                    # Fallback: the start row vanished (shouldn't happen) — record a
                    # complete row so the run is never lost from history.
                    session.add(
                        RunHistory(
                            zone_id=zone_id,
                            sequence_id=sequence_id,
                            started_at=started_at,
                            ended_at=off_time,
                            duration_min=actual_min,
                            liters=liters,
                            triggered_by=triggered_by,
                            aborted=aborted,
                            abort_reason=abort_reason,
                        )
                    )
                session.commit()

            # History is persisted — let consumers (MQTT stats) refresh totals.
            await self._emit_run_recorded()

            # Safety warning first, on *every* exit path: if the close was not
            # confirmed the valve may be physically open (the switch is retried by
            # retry_pending_closes). Surface it regardless of why the zone ended, so
            # a stop/watchdog/staircase/pause never hides an open valve.
            if not closed:
                logger.error(
                    "zone %s close unconfirmed (result=%s) — valve may be open; "
                    "the close will be retried",
                    zone_id,
                    result,
                )
                seq_label = seq.label or sequence_id
                await self._emit_notification(
                    translate(
                        "abort.close_failed",
                        self._config.language,
                        label=seq_label,
                        zone=zone_cfg.label,
                    ),
                    "warning",
                )

            if result == _STOP:
                _release()
                return
            if result == _WATCHDOG:
                logger.warning("Watchdog triggered for zone %s", zone_id)
                seq_label = seq.label or sequence_id
                await self._emit_notification(
                    translate(
                        "abort.watchdog",
                        self._config.language,
                        label=seq_label,
                        zone=zone_cfg.label,
                    ),
                    "warning",
                )
                _release()
                return
            if result == _RETRIGGER_FAILED:
                logger.warning(
                    "Staircase re-trigger failed for zone %s — ending run early", zone_id
                )
                seq_label = seq.label or sequence_id
                await self._emit_notification(
                    translate(
                        "abort.staircase_failed",
                        self._config.language,
                        label=seq_label,
                        zone=zone_cfg.label,
                    ),
                    "warning",
                )
                _release()
                return
            if result == _PAUSE:
                remaining = zone_duration - actual_min
                with self._session_factory() as session:
                    save_pause_snapshot(session, sequence_id, zone_id, i, max(0.0, remaining))
                _release()
                return

            # Normal zone completion, but the valve close was not confirmed: do NOT
            # advance to the next zone. Opening another valve while this one may
            # still be open can leave multiple zones running at once — dropping line
            # pressure and over-watering the unclosed zone. End the run here; the
            # open valve is durably tracked (PendingClose) and retried (the warning
            # was already emitted above).
            if not closed:
                _release()
                return

        # All zones completed normally.
        _release()
