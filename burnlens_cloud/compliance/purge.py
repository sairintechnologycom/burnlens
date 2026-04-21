"""Phase 3: scheduled PII purge for `workspace_activity`.

`workspace_activity` stores ip_address + user_agent alongside each action so
admins can audit access. These fields are PII/security-sensitive and should
not be retained indefinitely — after a cool-off window they offer little
incident-response value while inflating the blast radius of a DB leak.

This module runs a periodic UPDATE that NULL-outs those two columns on rows
older than the configured retention window. The row itself is preserved so
the audit log's action history and timestamps remain intact — only the PII
is redacted.

Design choices:

- UPDATE ... SET ip_address = NULL, user_agent = NULL WHERE created_at <
  NOW() - INTERVAL 'N days' AND (ip_address IS NOT NULL OR user_agent IS
  NOT NULL). The additional NOT NULL filter keeps the statement a no-op
  once everything in the window has been purged, so repeated ticks don't
  rewrite untouched pages.
- Runs once at app startup (catches any deploy gap) and then daily.
- Loop failures are logged but never take down the FastAPI server — the
  scheduler task catches exceptions per-tick.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..database import execute_insert

logger = logging.getLogger(__name__)


_PURGE_SQL = """
UPDATE workspace_activity
SET ip_address = NULL, user_agent = NULL
WHERE created_at < NOW() - ($1::int || ' days')::interval
  AND (ip_address IS NOT NULL OR user_agent IS NOT NULL)
"""


async def purge_old_activity_pii(retention_days: int | None = None) -> int:
    """Run one purge cycle. Returns the number of rows redacted.

    Safe to call from tests: resolves the pool, issues a single UPDATE, and
    returns the affected-row count parsed from asyncpg's command tag.
    """
    days = retention_days if retention_days is not None else settings.activity_pii_retention_days
    if days <= 0:
        # Defensive: a zero/negative window would redact everything immediately;
        # treat that as a misconfiguration and refuse rather than silently
        # nuking history.
        logger.warning("Phase 3 purge skipped: retention_days=%s is non-positive", days)
        return 0

    tag = await execute_insert(_PURGE_SQL, days)
    # asyncpg returns e.g. "UPDATE 42"; parse out the count defensively.
    try:
        count = int(tag.rsplit(" ", 1)[-1])
    except (ValueError, IndexError, AttributeError):
        count = 0
    if count:
        logger.info("Phase 3 purge: redacted ip/ua on %s workspace_activity rows older than %sd", count, days)
    return count


async def run_periodic_purge(initial_delay_s: int = 60, interval_s: int = 86400) -> None:
    """Background loop: initial purge on startup, then every `interval_s`.

    Exceptions are logged and the loop continues — a transient DB blip must
    not take down the FastAPI server.
    """
    # A small upfront delay so startup isn't blocked by the first purge in
    # the case of a large historical sweep.
    await asyncio.sleep(initial_delay_s)
    while True:
        try:
            await purge_old_activity_pii()
        except Exception as e:
            logger.exception("Phase 3 purge tick failed: %s", e)
        await asyncio.sleep(interval_s)
