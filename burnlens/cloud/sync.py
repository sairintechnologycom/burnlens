"""Cloud sync client — pushes anonymised cost data to burnlens.app backend.

Privacy guarantee: prompt content NEVER leaves the machine.
Only token counts, costs, model names, tags, and system_prompt_hash (SHA-256) are sent.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from burnlens.config import CloudConfig

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


class CloudSync:
    """Background sync client that pushes cost records to the hosted backend."""

    def __init__(self, config: CloudConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._running = False
        self.last_sync_at: datetime | None = None
        self.last_sync_count: int = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_connections=5),
            )
        return self._client

    async def close(self) -> None:
        """Shut down the HTTP client cleanly."""
        self._running = False
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def push_batch(self, records: list[dict[str, Any]]) -> bool:
        """POST a batch of anonymised records to the cloud endpoint.

        Returns True on HTTP 200, False on any error.
        Never raises — sync failure must not affect proxy.
        """
        try:
            client = await self._get_client()
            payload = {
                "api_key": self.config.api_key,
                "records": records,
            }
            resp = await client.post(
                self.config.endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                return True
            logger.warning(
                "Cloud sync got HTTP %d: %s", resp.status_code, resp.text[:200]
            )
            return False
        except Exception:
            logger.debug("Cloud sync push failed", exc_info=True)
            return False

    async def start_sync_loop(self, db_path: str) -> None:
        """Run the background sync loop until stopped.

        Every sync_interval_seconds:
        1. Query up to 500 un-synced records
        2. Push batch to cloud endpoint
        3. On success, mark records as synced
        """
        self._running = True
        logger.info(
            "Cloud sync started — interval %ds, endpoint %s",
            self.config.sync_interval_seconds,
            self.config.endpoint,
        )

        while self._running:
            try:
                await asyncio.sleep(self.config.sync_interval_seconds)
                await self._sync_once(db_path)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Cloud sync loop error", exc_info=True)

    async def _sync_once(self, db_path: str) -> int:
        """Run a single sync cycle. Returns the number of records pushed."""
        rows = await _fetch_unsynced(db_path, limit=_BATCH_SIZE)
        if not rows:
            return 0

        records = [_row_to_payload(row) for row in rows]
        ok = await self.push_batch(records)

        if ok:
            ids = [row["id"] for row in rows]
            await _mark_synced(db_path, ids)
            self.last_sync_at = datetime.now(timezone.utc)
            self.last_sync_count = len(ids)
            logger.info("Cloud sync pushed %d records", len(ids))
            return len(ids)
        return 0

    async def sync_now(self, db_path: str) -> int:
        """Manual one-shot sync. Returns total records pushed."""
        total = 0
        while True:
            count = await self._sync_once(db_path)
            total += count
            if count < _BATCH_SIZE:
                break
        return total


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def migrate_add_synced_at(db_path: str) -> None:
    """Add ``synced_at`` column to requests table if it doesn't exist.

    Safe to call multiple times — uses PRAGMA table_info to check.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "synced_at" not in columns:
            await db.execute(
                "ALTER TABLE requests ADD COLUMN synced_at TEXT"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_synced_at "
                "ON requests(synced_at)"
            )
            await db.commit()
            logger.info("Migration: added synced_at column to requests table")


async def get_unsynced_count(db_path: str) -> int:
    """Return the number of records that haven't been synced yet."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE synced_at IS NULL"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def _fetch_unsynced(
    db_path: str, limit: int = _BATCH_SIZE
) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` records that haven't been synced."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM requests WHERE synced_at IS NULL "
            "ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def _mark_synced(db_path: str, ids: list[int]) -> None:
    """Mark a batch of record IDs as synced."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        placeholders = ",".join("?" for _ in ids)
        await db.execute(
            f"UPDATE requests SET synced_at = ? WHERE id IN ({placeholders})",
            [now, *ids],
        )
        await db.commit()


def _row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a DB row to the cloud API payload format.

    Privacy: only hashes and metadata are sent — never raw prompt content.
    """
    tags = row.get("tags") or "{}"
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = {}

    return {
        "ts": row.get("timestamp"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "input_tokens": row.get("input_tokens", 0),
        "output_tokens": row.get("output_tokens", 0),
        "cost_usd": row.get("cost_usd", 0.0),
        "latency_ms": row.get("duration_ms", 0),
        "tag_feature": tags.get("feature"),
        "tag_team": tags.get("team"),
        "tag_customer": tags.get("customer"),
        "system_prompt_hash": row.get("system_prompt_hash"),
    }
