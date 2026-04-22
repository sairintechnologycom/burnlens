"""Daily retention-pruning loop.

Per QUOTA-05 and D-20..D-24:
- Runs once daily at ~03:00 UTC inside the FastAPI app process (single-pod Railway).
- Per workspace: DELETE request_records older than resolve_limits(workspace_id).retention_days.
- retention_days = 0 means retain-forever (D-23): skip the workspace.
- Batched 10,000 rows per transaction (D-21): short locks, friendly to the hot ingest path.
- Per-workspace failures are logged and swallowed (D-24): one bad workspace never aborts the run.
- Hard DELETE, not soft (D-22): the whole point is reclaiming storage.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..database import execute_insert, execute_query
from ..plans import resolve_limits

logger = logging.getLogger(__name__)


_BATCH_SIZE = 10_000
_PRUNE_HOUR_UTC = 3  # 03:00 UTC daily


def _seconds_until_next_03_utc(now: Optional[datetime] = None) -> float:
    """Seconds from `now` until the next 03:00 UTC. If now is >= 03:00 today, jump to tomorrow."""
    now = now or datetime.now(tz=timezone.utc)
    today_03 = now.replace(hour=_PRUNE_HOUR_UTC, minute=0, second=0, microsecond=0)
    target = today_03 if now < today_03 else today_03 + timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


def _parse_delete_count(tag: str) -> int:
    """Parse asyncpg command tag like 'DELETE 10000' -> 10000. Returns 0 on any error."""
    try:
        return int(tag.rsplit(" ", 1)[-1])
    except (AttributeError, ValueError, IndexError):
        return 0


async def _prune_workspace(workspace_id: str) -> int:
    """Delete expired request_records for a single workspace; returns total rows deleted.

    Skips (returns 0) if retention_days is None (plan has no limit) or 0 (retain-forever per D-23).
    Batches in chunks of _BATCH_SIZE and loops until a batch deletes fewer than _BATCH_SIZE rows.
    """
    limits = await resolve_limits(workspace_id)
    if limits is None:
        logger.debug("retention.skip workspace=%s limits=None (workspace missing)", workspace_id)
        return 0
    days = limits.retention_days
    if days is None or days == 0:
        logger.debug(
            "retention.skip workspace=%s days=%s (None=unlimited or 0=retain-forever)",
            workspace_id, days,
        )
        return 0

    total_deleted = 0
    started = time.monotonic()
    while True:
        tag = await execute_insert(
            """
            DELETE FROM request_records
            WHERE workspace_id = $1
              AND ts < (NOW() - make_interval(days => $2))
              AND id IN (
                  SELECT id FROM request_records
                  WHERE workspace_id = $1
                    AND ts < (NOW() - make_interval(days => $2))
                  LIMIT $3
              )
            """,
            workspace_id, days, _BATCH_SIZE,
        )
        batch = _parse_delete_count(tag)
        total_deleted += batch
        if batch < _BATCH_SIZE:
            break
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "retention.workspace_pruned workspace=%s days=%s deleted=%s elapsed_ms=%s",
        workspace_id, days, total_deleted, elapsed_ms,
    )
    return total_deleted


async def _run_prune_once() -> None:
    """Iterate every active workspace and prune it; per-workspace failures swallowed (D-24)."""
    started = time.monotonic()
    rows = await execute_query("SELECT id FROM workspaces WHERE active = true")
    total_workspaces = len(rows)
    total_deleted = 0
    failed = 0
    for row in rows:
        ws_id = str(row["id"])
        try:
            total_deleted += await _prune_workspace(ws_id)
        except Exception as exc:
            failed += 1
            logger.warning(
                "retention.workspace_failed workspace=%s err=%s",
                ws_id, exc, exc_info=True,
            )
    elapsed_s = time.monotonic() - started
    logger.info(
        "retention.run_complete workspaces=%s failed=%s total_rows_deleted=%s elapsed_s=%.1f",
        total_workspaces, failed, total_deleted, elapsed_s,
    )


async def run_periodic_retention_prune() -> None:
    """Background loop: sleep to 03:00 UTC, prune all workspaces, sleep ~24h, repeat.

    Exceptions inside a run are caught and logged; the loop never terminates on error.
    Cancellation (lifespan shutdown) propagates asyncio.CancelledError out of the sleep.
    """
    while True:
        delay = _seconds_until_next_03_utc()
        logger.info("retention.loop_sleep seconds_until_next_run=%.0f", delay)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("retention.loop_cancelled during sleep")
            raise
        try:
            await _run_prune_once()
        except Exception as exc:
            logger.exception("retention.run_tick_failed err=%s", exc)
        # Safety nap — ensure we don't burn through the next 03:00 window if the run was instant.
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("retention.loop_cancelled after run")
            raise
