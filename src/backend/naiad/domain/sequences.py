import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from naiad.config import AppConfig, ScheduleConfig, SequenceConfig, ZoneConfig
from naiad.domain.models import ActiveRun, RunHistory
from naiad.domain.resume import (
    clear_active_run,
    clear_all_snapshots,
    clear_snapshot,
    load_active_runs,
    load_snapshot,
    save_active_run,
    save_pause_snapshot,
)
from naiad.drivers.protocol import IValveDriver
from naiad.i18n import t as translate

logger = logging.getLogger(__name__)


class MutexConflict(Exception):
    """A run could not start because of a conflict with an active run."""


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
    stop_reason: str = "manual_stop"
    current_zone: ZoneProgress | None = None
    task: asyncio.Task[None] | None = None


_STOP = "stop"
_PAUSE = "pause"
_DONE = "done"
_WATCHDOG = "watchdog"


async def _wait_zone(
    duration_min: float,
    watchdog_min: float,
    stop_event: asyncio.Event,
    pause_event: asyncio.Event,
) -> str:
    zone_task = asyncio.ensure_future(asyncio.sleep(duration_min * 60))
    watchdog_task = asyncio.ensure_future(asyncio.sleep(watchdog_min * 60))
    stop_task = asyncio.ensure_future(stop_event.wait())
    pause_task = asyncio.ensure_future(pause_event.wait())

    done, pending = await asyncio.wait(
        [zone_task, watchdog_task, stop_task, pause_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    if stop_task in done:
        return _STOP
    if pause_task in done:
        return _PAUSE
    if watchdog_task in done:
        return _WATCHDOG
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
        # Invoked once a run actually opens its first valve (sequence_id, triggered_by),
        # so "running" is broadcast only after the run is confirmed, not when it's scheduled.
        self.on_started: Callable[[str, str], Awaitable[None]] | None = None
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

    def _zones_in_use(self, exclude_run: str | None = None) -> set[str]:
        """Every zone reserved by an active run.

        The full zone set of each running sequence is reserved (not just the
        currently-open zone), since a sequence still has to step through its
        remaining zones. Standalone zone runs carry a single-zone synthetic
        sequence, so this uniformly covers sequence and zone runs.
        """
        used: set[str] = set()
        for run_id, run in self._runs.items():
            if run_id == exclude_run:
                continue
            used.update(run.seq.zones)
        return used

    def _check_zone_conflict(self, zones: list[str]) -> None:
        conflict = sorted(set(zones) & self._zones_in_use())
        if conflict:
            raise ZoneBusy(conflict)

    def is_managed(self, zone_id: str) -> bool:
        return any(zone_id in run.seq.zones for run in self._runs.values())

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
    ) -> None:
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
    ) -> None:
        """Run a single zone in isolation for ``duration_min`` minutes.

        Runs in parallel with other runs as long as the zone is free (it must not
        already be reserved by a running sequence or another zone run), reusing
        the full execution path via a synthetic single-zone sequence.
        """
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
            logger.exception("Unhandled error in zone run '%s'", run.run_id)
            self._clear_active_run(run.run_id)
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
            logger.exception("Unhandled error in sequence '%s'", sequence_id)
            self._clear_active_run(sequence_id)
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
        self, zone_cfg: Any, zone_id: str, attempts: int = 3, backoff_s: float = 1.0
    ) -> bool:
        """Turn a zone off, retrying on failure. Never raises.

        A failing turn_off (e.g. HA disconnected) must not abort the run loop
        before history is recorded, and must not leave the loop in a state where
        the valve is silently assumed off. Returns True if HA confirmed the
        command, False if the valve may still be physically open.
        """
        for attempt in range(1, attempts + 1):
            try:
                await self._driver.turn_off(zone_cfg)
                return True
            except Exception:
                logger.warning(
                    "turn_off failed for zone %s (attempt %d/%d)",
                    zone_id,
                    attempt,
                    attempts,
                    exc_info=True,
                )
                if attempt < attempts:
                    await asyncio.sleep(backoff_s)
        logger.error(
            "Could not turn off zone %s after %d attempts — valve may still be open; "
            "it will be closed by reconciliation once HA is reachable",
            zone_id,
            attempts,
        )
        return False

    async def reconcile_valves(self, exclude: set[str] | str | None = None) -> None:
        """Turn off every configured zone except the live/excluded ones.

        Safety net for valves left ON by a previous process / crash, and for
        closing a zone after an HA disconnect aborted its run. ``exclude`` keeps
        specific zones open (used when resuming runs that own those zones); the
        zones of all currently-live runs are kept open implicitly.
        Idempotent: turning off an already-off switch is harmless.
        """
        if exclude is None:
            excluded: set[str] = set()
        elif isinstance(exclude, str):
            excluded = {exclude}
        else:
            excluded = set(exclude)
        running_zones = {
            run.current_zone.zone_id for run in self._runs.values() if run.current_zone is not None
        }
        keep = excluded | running_zones
        for zone_id, zone_cfg in self._config.zones.items():
            if zone_id in keep:
                continue
            await self._safe_turn_off(zone_cfg, zone_id, attempts=1)

    def _clear_active_run(self, sequence_id: str) -> None:
        with self._session_factory() as session:
            clear_active_run(session, sequence_id)

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
        return actions

    def _recover_one(self, record: ActiveRun) -> tuple[str, str | None]:
        """Process one persisted run; returns (action, resuming_zone_or_None).

        Registers a live ``_Run`` and starts its recovery task when resuming.
        Does not close valves itself — the caller reconciles once at the end.
        """
        seq = self._config.sequences.get(record.sequence_id)
        if seq is None or record.zone_index >= len(seq.zones):
            logger.warning(
                "Crash recovery: discarding active run for unknown sequence/zone '%s'",
                record.sequence_id,
            )
            self._clear_active_run(record.sequence_id)
            return "discarded", None

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
            self._clear_active_run(record.sequence_id)
            return "closed_stale", None

        remaining = max(0.0, min(record.zone_planned_min, record.zone_planned_min - elapsed))
        resuming_zone = seq.zones[record.zone_index]
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
            logger.exception("Unhandled error during crash recovery of '%s'", run.run_id)
            self._clear_active_run(run.run_id)
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
                    session, sequence_id, i, started_at, zone_duration, duration_min, triggered_by
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
            await self._driver.turn_on(zone_cfg)
            logger.info("zone %s ON  (%.1f min)", zone_id, zone_duration)

            if not announced and self.on_started is not None:
                announced = True
                try:
                    await self.on_started(sequence_id, triggered_by)
                except Exception:
                    logger.exception("on_started callback failed for '%s'", sequence_id)

            result = await _wait_zone(
                zone_duration, effective_watchdog, run.stop_event, run.pause_event
            )

            off_time = datetime.now(UTC)
            await self._safe_turn_off(zone_cfg, zone_id)
            logger.info("zone %s OFF result=%s", zone_id, result)

            actual_min = (off_time - started_at).total_seconds() / 60.0
            liters = actual_min / 60.0 * zone_cfg.flow_lph
            aborted = result in (_STOP, _WATCHDOG)

            abort_reason: str | None = None
            if result == _WATCHDOG:
                abort_reason = "watchdog"
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

            if result == _STOP:
                self._clear_active_run(sequence_id)
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
                self._clear_active_run(sequence_id)
                return
            if result == _PAUSE:
                remaining = zone_duration - actual_min
                with self._session_factory() as session:
                    save_pause_snapshot(session, sequence_id, zone_id, i, max(0.0, remaining))
                self._clear_active_run(sequence_id)
                return

        # All zones completed normally.
        self._clear_active_run(sequence_id)
