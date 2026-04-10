"""APScheduler wiring for hourly detection runs.

Provides a module-level scheduler singleton and job registration functions.
The scheduler is started by the FastAPI lifespan and stopped on shutdown.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from burnlens.detection.billing import run_all_parsers
from burnlens.detection.classifier import classify_new_assets

if TYPE_CHECKING:
    from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

# Module-level scheduler singleton
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the module-level AsyncIOScheduler singleton, creating it if needed.

    Subsequent calls return the same instance. Use reset_scheduler() in tests
    to get a fresh instance.

    Returns:
        The shared AsyncIOScheduler instance.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def reset_scheduler() -> None:
    """Reset the module-level scheduler singleton to None.

    Intended for use in tests so each test gets a fresh scheduler.
    """
    global _scheduler
    _scheduler = None


def register_detection_jobs(
    scheduler: AsyncIOScheduler,
    db_path: str,
    config: "BurnLensConfig",
) -> None:
    """Register the hourly detection job on the given scheduler.

    The first run is deferred by 1 hour to avoid running detection
    immediately on startup (which may happen before the proxy has
    processed any traffic).

    Args:
        scheduler: The AsyncIOScheduler to register jobs on.
        db_path: Path to the BurnLens SQLite database.
        config: BurnLensConfig with admin key fields populated.
    """
    first_run = datetime.now(timezone.utc) + timedelta(hours=1)

    scheduler.add_job(
        run_detection,
        trigger=IntervalTrigger(hours=1),
        id="detection_hourly",
        replace_existing=True,
        next_run_time=first_run,
        kwargs={"db_path": db_path, "config": config},
    )
    logger.info(
        "Detection job registered — hourly, first run at %s",
        first_run.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


async def run_detection(db_path: str, config: "BurnLensConfig") -> None:
    """Run all billing parsers and classify new assets.

    Calls run_all_parsers (billing API detection) followed by
    classify_new_assets (provider signature matching for shadow assets).

    This function is designed to fail open: any exception is caught,
    logged, and swallowed so that scheduler failures never crash the proxy.

    Args:
        db_path: Path to the BurnLens SQLite database.
        config: BurnLensConfig with admin key fields populated.
    """
    try:
        logger.info("Starting detection run")
        await run_all_parsers(db_path, config)
        classified = await classify_new_assets(db_path)
        logger.info("Detection run complete — classified %d shadow assets", classified)
    except Exception:
        logger.error("Detection run failed", exc_info=True)
