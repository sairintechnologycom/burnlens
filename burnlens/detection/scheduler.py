"""APScheduler wiring for hourly detection runs and alert jobs.

Provides a module-level scheduler singleton and job registration functions.
The scheduler is started by the FastAPI lifespan and stopped on shutdown.

Jobs registered:
  - detection_hourly: hourly billing parser + asset classifier
  - discovery_alerts_hourly: hourly shadow/provider/spend-spike alert checks
  - daily_digest: daily 8 AM UTC digest of model changes
  - weekly_digest: Monday 8 AM UTC digest of inactive assets
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

from burnlens.detection.billing import run_all_parsers
from burnlens.detection.classifier import classify_new_assets
from burnlens.storage.database import archive_old_discovery_events, purge_old_fired_alerts
from burnlens.alerts.discovery import DiscoveryAlertEngine
from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

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
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
    config: BurnLensConfig,
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
    from apscheduler.triggers.interval import IntervalTrigger

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


async def run_detection(db_path: str, config: BurnLensConfig) -> None:
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


def register_alert_jobs(
    scheduler: AsyncIOScheduler,
    db_path: str,
    config: BurnLensConfig,
    discovery_engine: DiscoveryAlertEngine,
) -> None:
    """Register the three recurring alert jobs on the given scheduler.

    Jobs registered:
      - discovery_alerts_hourly: calls DiscoveryAlertEngine.run_all_checks()
        every hour (first run deferred 1 hour, consistent with detection_hourly)
      - daily_digest: sends model-change digest email at 8 AM UTC daily
      - weekly_digest: sends inactive-asset digest email at 8 AM UTC on Mondays

    All jobs are fail-open: wrapper functions catch and log exceptions so
    that a failure in one job never crashes the scheduler or proxy.

    Args:
        scheduler:        The AsyncIOScheduler to register jobs on.
        db_path:          Path to the BurnLens SQLite database.
        config:           BurnLensConfig with alerts and email configuration.
        discovery_engine: Configured DiscoveryAlertEngine instance.
    """
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    first_run = datetime.now(timezone.utc) + timedelta(hours=1)

    scheduler.add_job(
        _run_discovery_alerts,
        trigger=IntervalTrigger(hours=1),
        id="discovery_alerts_hourly",
        replace_existing=True,
        next_run_time=first_run,
        kwargs={"discovery_engine": discovery_engine},
    )

    scheduler.add_job(
        _run_daily_digest,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_digest",
        replace_existing=True,
        kwargs={"db_path": db_path, "config": config},
    )

    scheduler.add_job(
        _run_weekly_digest,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_digest",
        replace_existing=True,
        kwargs={"db_path": db_path, "config": config},
    )

    scheduler.add_job(
        _purge_old_fired_alerts,
        trigger=CronTrigger(hour=3, minute=0),
        id="purge_fired_alerts",
        replace_existing=True,
        kwargs={"db_path": db_path},
    )

    scheduler.add_job(
        _run_discovery_events_archival,
        trigger=CronTrigger(hour=2, minute=0),
        id="discovery_events_archival",
        replace_existing=True,
        misfire_grace_time=3600,
        kwargs={"db_path": db_path},
    )

    logger.info(
        "Alert jobs registered (hourly discovery, daily digest at 08:00 UTC, "
        "weekly digest Mon 08:00 UTC, nightly fired_alerts purge at 03:00 UTC, "
        "nightly discovery_events archival at 02:00 UTC)"
    )


async def _run_discovery_alerts(discovery_engine: DiscoveryAlertEngine) -> None:
    """Run all DiscoveryAlertEngine checks.  Fail-open wrapper for the scheduler.

    Args:
        discovery_engine: Configured DiscoveryAlertEngine instance.
    """
    try:
        await discovery_engine.run_all_checks()
    except Exception:
        logger.error("Discovery alert check failed", exc_info=True)


async def _run_daily_digest(db_path: str, config: BurnLensConfig) -> None:
    """Create an EmailSender and send the daily model-change digest.  Fail-open.

    Args:
        db_path: Path to the BurnLens SQLite database.
        config:  BurnLensConfig with email and alert_recipients configured.
    """
    try:
        from burnlens.alerts.digests import send_daily_digest
        from burnlens.alerts.email import EmailSender

        sender = EmailSender(config.email)
        count = await send_daily_digest(db_path, sender, config.alerts.alert_recipients)
        logger.info("Daily digest sent — %d model change events included", count)
    except Exception:
        logger.error("Daily digest failed", exc_info=True)


async def _run_weekly_digest(db_path: str, config: BurnLensConfig) -> None:
    """Create an EmailSender and send the weekly inactive-asset digest.  Fail-open.

    Args:
        db_path: Path to the BurnLens SQLite database.
        config:  BurnLensConfig with email and alert_recipients configured.
    """
    try:
        from burnlens.alerts.digests import send_weekly_digest
        from burnlens.alerts.email import EmailSender

        sender = EmailSender(config.email)
        count = await send_weekly_digest(db_path, sender, config.alerts.alert_recipients)
        logger.info("Weekly digest sent — %d inactive assets included", count)
    except Exception:
        logger.error("Weekly digest failed", exc_info=True)


async def _purge_old_fired_alerts(db_path: str) -> None:
    """Delete fired_alerts records older than 30 days to prevent unbounded growth.

    Runs nightly at 03:00 UTC.  Fail-open.
    """
    try:
        deleted = await purge_old_fired_alerts(db_path, older_than_days=30)
        if deleted:
            logger.info("Purged %d old fired_alerts records", deleted)
    except Exception:
        logger.error("fired_alerts purge failed", exc_info=True)


async def _run_discovery_events_archival(db_path: str) -> None:
    """Archive discovery_events older than 90 days.

    Runs nightly at 02:00 UTC.  Fail-open.
    """
    try:
        count = await archive_old_discovery_events(db_path, retention_days=90)
        if count > 0:
            logger.info("Archived %d discovery events older than 90 days", count)
    except Exception:
        logger.error("Discovery events archival failed", exc_info=True)
