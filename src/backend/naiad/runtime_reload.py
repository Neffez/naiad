"""Apply a reloaded configuration to the live runtime without a restart.

The whole runtime shares a single AppConfig instance: the runner reads it live,
and the scheduler jobs / sensor listeners capture it by reference. So a reload
mutates that shared instance in place (preserving its identity) and then refreshes
the few derived structures that don't track it automatically — the sequence cron
jobs and the liter tracker's switch→zone map.
"""

import logging
from collections.abc import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session

from naiad.config import AppConfig
from naiad.domain.sequences import SequenceRunner
from naiad.domain.tracking import LiterTracker
from naiad.ha_client import HAClient
from naiad.scheduler import reschedule_sequences

logger = logging.getLogger(__name__)


def mutate_config_in_place(current: AppConfig, fresh: AppConfig) -> None:
    """Copy every top-level field from ``fresh`` onto ``current``, keeping the
    object identity that the rest of the runtime holds by reference."""
    for name in AppConfig.model_fields:
        setattr(current, name, getattr(fresh, name))


def apply_reloaded_config(
    current_config: AppConfig,
    fresh_config: AppConfig,
    *,
    scheduler: AsyncIOScheduler,
    runner: SequenceRunner,
    ha: HAClient,
    session_factory: Callable[[], Session],
    tracker: LiterTracker | None = None,
) -> None:
    """Apply ``fresh_config`` to the running system in place."""
    mutate_config_in_place(current_config, fresh_config)
    reschedule_sequences(scheduler, current_config, runner, ha, session_factory)
    if tracker is not None:
        tracker.rebuild_zone_map()
    logger.info(
        "Configuration reloaded",
        extra={"zones": len(current_config.zones), "sequences": len(current_config.sequences)},
    )
