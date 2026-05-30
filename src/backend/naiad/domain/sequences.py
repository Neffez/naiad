import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from naiad.config import AppConfig, SequenceConfig
from naiad.domain.models import ActiveRun, RunHistory
from naiad.domain.resume import (
    clear_active_run,
    clear_orphan_snapshot,
    clear_snapshot,
    load_active_run,
    load_snapshot,
    save_active_run,
    save_pause_snapshot,
)
from naiad.drivers.protocol import IValveDriver

logger = logging.getLogger(__name__)


class MutexConflict(Exception):
    """Another sequence is already running."""


class SequenceNotFound(Exception):
    """Sequence ID does not exist in config."""


class NotRunning(Exception):
    """No sequence is currently running."""


class SequenceState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    # NOTE: PAUSED is never returned by SequenceRunner.status() — on pause the run
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
        self._running: str | None = None
        self._current_zone: ZoneProgress | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._pause_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stop_reason: str = "manual_stop"
        self._triggered_by: str = "manual"
        # Invoked once a run actually opens its first valve (sequence_id, triggered_by),
        # so "running" is broadcast only after the run is confirmed, not when it's scheduled.
        self.on_started: Callable[[str, str], Awaitable[None]] | None = None
        # Invoked for noteworthy run events that warrant a notification
        # (message, level), e.g. a watchdog abort. Wired to push/broadcast in main.
        self.on_notification: Callable[[str, str], Awaitable[None]] | None = None

    async def _emit_notification(self, message: str, level: str) -> None:
        if self.on_notification is None:
            return
        try:
            await self.on_notification(message, level)
        except Exception:
            logger.exception("on_notification callback failed")

    def is_managed(self, zone_id: str) -> bool:
        if self._running is None:
            return False
        seq = self._config.sequences.get(self._running)
        return seq is not None and zone_id in seq.zones

    def status(self) -> SequenceStatus:
        """Live in-memory state: only IDLE or RUNNING. A paused run reads as IDLE
        here; the PAUSED state is reconstructed from the ResumeSnapshot at the API
        layer."""
        if self._running is None:
            return SequenceStatus(state=SequenceState.IDLE)
        return SequenceStatus(
            state=SequenceState.RUNNING,
            sequence_id=self._running,
            current_zone=self._current_zone,
            triggered_by=self._triggered_by,
        )

    async def start(
        self,
        sequence_id: str,
        factor_pct: float = 100.0,
        override_min: float | None = None,
        triggered_by: str = "manual",
    ) -> None:
        if sequence_id not in self._config.sequences:
            raise SequenceNotFound(sequence_id)
        if self._running is not None:
            raise MutexConflict(f"'{self._running}' is already running")

        self._running = sequence_id  # set before first await — asyncio mutex
        self._stop_event.clear()
        self._pause_event.clear()
        self._stop_reason = "manual_stop"
        self._triggered_by = triggered_by

        self._task = asyncio.create_task(
            self._execute(sequence_id, factor_pct, override_min, triggered_by),
            name=f"seq-{sequence_id}",
        )

    async def stop(self, reason: str = "manual_stop") -> None:
        if self._running is None:
            raise NotRunning
        self._stop_reason = reason
        with self._session_factory() as session:
            clear_snapshot(session, self._running)
        self._stop_event.set()
        if self._task:
            await self._task

    async def pause(self) -> None:
        if self._running is None:
            raise NotRunning
        self._pause_event.set()
        if self._task:
            await self._task

    def discard_snapshot(self, sequence_id: str) -> None:
        """Drop a paused sequence's resume snapshot (cancel without resuming)."""
        with self._session_factory() as session:
            clear_snapshot(session, sequence_id)

    async def _execute(
        self,
        sequence_id: str,
        factor_pct: float,
        override_min: float | None = None,
        triggered_by: str = "manual",
    ) -> None:
        seq = self._config.sequences[sequence_id]
        try:
            with self._session_factory() as session:
                clear_orphan_snapshot(session, sequence_id)  # abandon a different paused seq
                snapshot = load_snapshot(session, sequence_id)

            start_index = 0
            start_remaining: float | None = None
            if snapshot is not None:
                start_index = snapshot.zone_index
                start_remaining = snapshot.remaining_min
                triggered_by = "resume"
                with self._session_factory() as session:
                    clear_snapshot(session, sequence_id)

            await self._run_zones(
                sequence_id,
                seq,
                factor_pct,
                start_index,
                start_remaining,
                override_min,
                triggered_by,
            )
        except asyncio.CancelledError:
            # Process shutdown/restart — keep the ActiveRun record so the run can
            # be recovered on the next boot. Re-raise without clearing it.
            raise
        except Exception:
            logger.exception("Unhandled error in sequence '%s'", sequence_id)
            self._clear_active_run()
        finally:
            self._running = None
            self._current_zone = None
            self._task = None

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

    async def reconcile_valves(self, exclude: str | None = None) -> None:
        """Turn off every configured zone except the live/excluded one.

        Safety net for valves left ON by a previous process / crash, and for
        closing a zone after an HA disconnect aborted its run. ``exclude`` keeps
        a specific zone open (used when resuming a run owns that zone).
        Idempotent: turning off an already-off switch is harmless.
        """
        running_zone = self._current_zone.zone_id if self._current_zone else None
        for zone_id, zone_cfg in self._config.zones.items():
            if zone_id in (running_zone, exclude):
                continue
            await self._safe_turn_off(zone_cfg, zone_id, attempts=1)

    def _clear_active_run(self) -> None:
        with self._session_factory() as session:
            clear_active_run(session)

    async def recover_run(self) -> str:
        """Recover (or clean up) an in-flight run after a crash/restart.

        Called once when HA first becomes reachable. Policy ("zone duration as
        the bound"): if the current zone's planned window has **not** elapsed,
        resume it for the remaining time and continue the following zones;
        otherwise the run is stale → close all valves and discard it. In every
        non-resume branch any orphaned valve is also closed. Returns the action
        taken (for logging/tests).
        """
        with self._session_factory() as session:
            record = load_active_run(session)

        if record is None:
            await self.reconcile_valves()
            return "reconciled"

        seq = self._config.sequences.get(record.sequence_id)
        if seq is None or record.zone_index >= len(seq.zones):
            logger.warning(
                "Crash recovery: discarding active run for unknown sequence/zone '%s'",
                record.sequence_id,
            )
            self._clear_active_run()
            await self.reconcile_valves()
            return "discarded"

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
            self._clear_active_run()
            await self.reconcile_valves()
            return "closed_stale"

        remaining = max(0.0, min(record.zone_planned_min, record.zone_planned_min - elapsed))
        resuming_zone = seq.zones[record.zone_index]
        logger.info(
            "Crash recovery: resuming '%s' at zone '%s' (#%d) for %.1f more min",
            record.sequence_id,
            resuming_zone,
            record.zone_index,
            remaining,
        )

        self._running = record.sequence_id  # claim the mutex before awaiting
        await self.reconcile_valves(exclude=resuming_zone)  # close any other orphan valves
        self._stop_event.clear()
        self._pause_event.clear()
        self._stop_reason = "manual_stop"
        self._triggered_by = "resume"
        self._task = asyncio.create_task(
            self._recover_execute(record, remaining),
            name=f"seq-resume-{record.sequence_id}",
        )
        return "resumed"

    async def _recover_execute(self, record: ActiveRun, remaining_min: float) -> None:
        seq = self._config.sequences[record.sequence_id]
        try:
            await self._run_zones(
                record.sequence_id,
                seq,
                factor_pct=100.0,
                start_index=record.zone_index,
                start_remaining=remaining_min,
                override_min=record.run_duration_min,
                triggered_by="resume",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unhandled error during crash recovery of '%s'", record.sequence_id)
            self._clear_active_run()
        finally:
            self._running = None
            self._current_zone = None
            self._task = None

    async def _run_zones(
        self,
        sequence_id: str,
        seq: SequenceConfig,
        factor_pct: float,
        start_index: int,
        start_remaining: float | None,
        override_min: float | None = None,
        triggered_by: str = "manual",
    ) -> None:
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
            self._current_zone = ZoneProgress(
                zone_id=zone_id, started_at=started_at, duration_min=zone_duration
            )
            # Persist the in-flight state so a hard crash can recover (see ActiveRun).
            with self._session_factory() as session:
                save_active_run(
                    session, sequence_id, i, started_at, zone_duration, duration_min, triggered_by
                )
            await self._driver.turn_on(zone_cfg)
            logger.info("zone %s ON  (%.1f min)", zone_id, zone_duration)

            if not announced and self.on_started is not None:
                announced = True
                try:
                    await self.on_started(sequence_id, triggered_by)
                except Exception:
                    logger.exception("on_started callback failed for '%s'", sequence_id)

            result = await _wait_zone(
                zone_duration, effective_watchdog, self._stop_event, self._pause_event
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
                abort_reason = self._stop_reason

            with self._session_factory() as session:
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

            if result == _STOP:
                self._clear_active_run()
                return
            if result == _WATCHDOG:
                logger.warning("Watchdog triggered for zone %s", zone_id)
                seq_label = seq.label or sequence_id
                await self._emit_notification(
                    f"🚨 Watchdog: {seq_label} — Zone {zone_cfg.label} lief zu lange, gestoppt.",
                    "warning",
                )
                self._clear_active_run()
                return
            if result == _PAUSE:
                remaining = zone_duration - actual_min
                with self._session_factory() as session:
                    save_pause_snapshot(session, sequence_id, zone_id, i, max(0.0, remaining))
                self._clear_active_run()
                return

        # All zones completed normally.
        self._clear_active_run()
