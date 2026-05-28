import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from naiad.config import AppConfig, SequenceConfig
from naiad.domain.models import RunHistory
from naiad.domain.resume import clear_snapshot, load_snapshot, save_pause_snapshot
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
        self._stop_event: asyncio.Event = asyncio.Event()
        self._pause_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def is_managed(self, zone_id: str) -> bool:
        if self._running is None:
            return False
        seq = self._config.sequences.get(self._running)
        return seq is not None and zone_id in seq.zones

    def status(self) -> SequenceStatus:
        if self._running is None:
            return SequenceStatus(state=SequenceState.IDLE)
        return SequenceStatus(
            state=SequenceState.RUNNING,
            sequence_id=self._running,
        )

    async def start(self, sequence_id: str, factor_pct: float = 100.0) -> None:
        if sequence_id not in self._config.sequences:
            raise SequenceNotFound(sequence_id)
        if self._running is not None:
            raise MutexConflict(f"'{self._running}' is already running")

        self._running = sequence_id  # set before first await — asyncio mutex
        self._stop_event.clear()
        self._pause_event.clear()

        self._task = asyncio.create_task(
            self._execute(sequence_id, factor_pct),
            name=f"seq-{sequence_id}",
        )

    async def stop(self) -> None:
        if self._running is None:
            raise NotRunning
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

    async def _execute(self, sequence_id: str, factor_pct: float) -> None:
        seq = self._config.sequences[sequence_id]
        try:
            with self._session_factory() as session:
                snapshot = load_snapshot(session, sequence_id)

            start_index = 0
            start_remaining: float | None = None
            if snapshot is not None:
                start_index = snapshot.zone_index
                start_remaining = snapshot.remaining_min
                with self._session_factory() as session:
                    clear_snapshot(session, sequence_id)

            await self._run_zones(
                sequence_id, seq, factor_pct, start_index, start_remaining
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unhandled error in sequence '%s'", sequence_id)
        finally:
            self._running = None
            self._task = None

    async def _run_zones(
        self,
        sequence_id: str,
        seq: SequenceConfig,
        factor_pct: float,
        start_index: int,
        start_remaining: float | None,
    ) -> None:
        lo, hi = seq.range
        basis = seq.basis_min_per_zone * factor_pct / 100.0
        duration_min = max(float(lo), min(float(hi), basis))

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
            await self._driver.turn_on(zone_cfg)
            logger.info("zone %s ON  (%.1f min)", zone_id, zone_duration)

            result = await _wait_zone(
                zone_duration, seq.watchdog_min, self._stop_event, self._pause_event
            )

            off_time = datetime.now(UTC)
            await self._driver.turn_off(zone_cfg)
            logger.info("zone %s OFF result=%s", zone_id, result)

            actual_min = (off_time - started_at).total_seconds() / 60.0
            liters = actual_min / 60.0 * zone_cfg.flow_lph
            aborted = result in (_STOP, _WATCHDOG)

            with self._session_factory() as session:
                session.add(RunHistory(
                    zone_id=zone_id,
                    sequence_id=sequence_id,
                    started_at=started_at,
                    ended_at=off_time,
                    duration_min=actual_min,
                    liters=liters,
                    triggered_by="sequence",
                    aborted=aborted,
                ))
                session.commit()

            if result == _STOP:
                return
            if result == _WATCHDOG:
                logger.warning("Watchdog triggered for zone %s", zone_id)
                return
            if result == _PAUSE:
                remaining = zone_duration - actual_min
                with self._session_factory() as session:
                    save_pause_snapshot(session, sequence_id, zone_id, i, max(0.0, remaining))
                return
