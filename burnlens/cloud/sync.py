"""Cloud sync client -- pushes anonymised cost data to burnlens.app backend.

Privacy guarantee: prompt content NEVER leaves the machine.
Only token counts, costs, model names, opted-in tags, and a keyed prompt
fingerprint are sent.
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

# Tags allowed to leave the local machine, as bare tag names.
#
# This tuple is the single source of truth for the three hops a tag has to
# survive on its way to the cloud: the flattened wire payload
# (:func:`_row_to_payload`), the privacy whitelist (:data:`SYNC_ALLOWED_FIELDS`)
# and the backend's re-nesting map (``burnlens_cloud.models._lift_flat_tags``).
# Historically each hop was hand-maintained, so a tag added to the interceptor's
# ``_ALLOWED_TAGS`` reached SQLite and then vanished silently. Deriving the
# whitelist and the payload from one list removes two of those hops;
# tests/test_tag_plumbing_wired.py guards the third.
#
# Tags NOT listed here stay local deliberately: repo/branch/dev/pr/commit_sha
# name private code and people, and app_id/env/service are not yet modelled
# backend-side. Adding one is a privacy decision, not a plumbing detail.
CLOUD_SYNCED_TAGS: tuple[str, ...] = (
    "feature",
    "team",
    "customer",
    "key_label",
    "agent_id",
    "workflow_id",
    # Run key for the hosted Run -> Step view. A session id is the coding-agent
    # JSONL filename stem -- an opaque UUID naming no code, no person and no
    # prompt content -- so it carries the same linkability as trace_id, which
    # already syncs. Approved deliberately 2026-08-13, not defaulted.
    "session",
)

SYNC_ALLOWED_FIELDS = frozenset({
    "timestamp",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "duration_ms",
    "status_code",
    "system_prompt_hash",
    "cache_hit",
    "cache_saved_usd",
    "tool_calls",
    "trace_id",
    "parent_span_id",
    "event_id",
    "request_id",
    "source",
} | {f"tag_{name}" for name in CLOUD_SYNCED_TAGS})


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Strip a record down to only the privacy-allowed fields."""
    return {k: v for k, v in record.items() if k in SYNC_ALLOWED_FIELDS}


def _pseudonymize_prompt_hash(value: Any, api_key: str) -> str | None:
    """Turn the local SHA-256 prompt hash into a workspace-keyed fingerprint.

    A plain hash of a common system prompt can be matched against a dictionary
    of likely prompts.  Keying the value with the workspace ingest secret keeps
    duplicate detection stable within a workspace while preventing offline
    matching by somebody who sees only the cloud database.
    """
    if not value:
        return None
    import hashlib
    import hmac

    return hmac.new(
        api_key.encode("utf-8"),
        str(value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class CloudSync:
    """Background sync client that pushes cost records to the hosted backend."""

    def __init__(self, config: "BurnLensConfig") -> None:
        self.config = config
        self.cloud_config = config.cloud
        self._client: httpx.AsyncClient | None = None
        self._running = False
        self.last_sync_at = None
        self.last_sync_count = 0
        self._backoff_until = 0

    def _get_client(self) -> httpx.AsyncClient:
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

    def _apply_routing_overrides(self, overrides: dict[str, Any]) -> None:
        """Update local routing config with values from cloud (Phase 10)."""
        try:
            if "budget_downgrade" in overrides:
                self.config.routing.budget_downgrade = bool(overrides["budget_downgrade"])
            if "downgrade_threshold_pct" in overrides:
                self.config.routing.downgrade_threshold_pct = float(
                    overrides["downgrade_threshold_pct"]
                )
            logger.debug("Cloud sync: applied routing overrides %s", overrides)
        except (ValueError, TypeError) as exc:
            logger.warning("Cloud sync: failed to apply routing overrides: %s", exc)

    def _api_base(self) -> str:
        """Strip any ingest path off the configured endpoint to get the API root.

        Configs written before 1.4.2 (including the old default) pointed at
        /api/v1/ingest — a path that never existed on the backend (404) — so
        both that and the correct /v1/ingest have to be tolerated here. Every
        route is then built from this root, so a second endpoint cannot
        rediscover the same 404.
        """
        endpoint = self.cloud_config.endpoint.rstrip("/")
        for suffix in ("/api/v1/ingest", "/v1/ingest"):
            if endpoint.endswith(suffix):
                return endpoint[: -len(suffix)]
        return endpoint

    async def push_outcomes(self, outcomes: list[dict[str, Any]]) -> bool:
        """POST a batch of outcomes to the cloud. True on HTTP 200.

        Unlike cost records these are user-authored business events, not
        auto-captured traffic, so there is no field whitelist to apply — the
        caller chose every value.
        """
        import time

        if time.monotonic() < self._backoff_until:
            return False
        if not outcomes:
            return False

        client = self._get_client()
        api_key = self.cloud_config.api_key or ""
        try:
            resp = await client.post(
                self._api_base() + "/v1/outcomes",
                json={"outcomes": outcomes},
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                    "X-Requested-With": "burnlens-sync",
                },
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 404:
                # Backend predates outcomes. Not an error worth retrying every
                # tick — leave them unsynced and say so once.
                logger.debug("Cloud sync: backend has no /v1/outcomes endpoint")
                return False
            logger.warning(
                "Cloud sync: outcome push failed with HTTP %d", resp.status_code
            )
            return False
        except httpx.HTTPError as exc:
            logger.debug("Cloud sync: outcome push error: %s", exc)
            return False

    async def push_batch(self, records: list[dict[str, Any]]) -> bool:
        """POST a batch of sanitized records to the cloud ingest endpoint.

        Returns True on HTTP 200, False on any error.
        """
        import time

        if time.monotonic() < self._backoff_until:
            logger.debug("Cloud sync: still in backoff period, skipping")
            return False

        if not records:
            return False

        client = self._get_client()
        api_key = self.cloud_config.api_key or ""
        sanitized = [_sanitize_record(r) for r in records]
        for record in sanitized:
            record["system_prompt_hash"] = _pseudonymize_prompt_hash(
                record.get("system_prompt_hash"), api_key
            )

        url = self._api_base() + "/v1/ingest"

        try:
            resp = await client.post(
                url,
                json={"records": sanitized},
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                    # Backends running the CSRF middleware without the
                    # machine-endpoint exemption 403 requests lacking this.
                    "X-Requested-With": "burnlens-sync",
                },
            )

            if resp.status_code == 200:
                # Older/self-hosted ingest deployments may return an empty 200
                # body. Routing overrides are optional, so successful delivery
                # must not be retried merely because no JSON document exists.
                try:
                    data = resp.json()
                except (ValueError, json.JSONDecodeError):
                    data = {}
                overrides = data.get("routing_overrides")
                if overrides:
                    self._apply_routing_overrides(overrides)
                return True

            if resp.status_code == 401:
                logger.error("Cloud sync: invalid API key — run burnlens login")
                self._running = False
                return False

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "60"))
                import time as _time
                self._backoff_until = _time.monotonic() + retry_after
                logger.warning("Cloud sync: free tier limit reached — upgrade at burnlens.app")
                return False

            if resp.status_code >= 500:
                logger.warning(
                    "Cloud sync: server error HTTP %d — will retry next cycle",
                    resp.status_code,
                )
                return False

            logger.warning("Cloud sync got HTTP %d: %s", resp.status_code, resp.text)
            return False

        except Exception as exc:
            logger.warning("Cloud sync: network error (%s)", type(exc).__name__)
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
            self.cloud_config.sync_interval_seconds,
            self.cloud_config.endpoint,
        )

        while self._running:
            try:
                await asyncio.sleep(self.cloud_config.sync_interval_seconds)
                await self._sync_once(db_path)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Cloud sync loop error", exc_info=True)

    async def _sync_outcomes_once(self, db_path: str) -> int:
        """Push pending outcomes. Returns how many were pushed.

        Deliberately independent of the cost-record push: outcomes are low
        volume and a backend that cannot accept them yet must not stall cost
        sync, which is the product's primary job.
        """
        rows = await _fetch_unsynced_outcomes(db_path, limit=_BATCH_SIZE)
        if not rows:
            return 0

        ok = await self.push_outcomes([_outcome_row_to_payload(r) for r in rows])
        if not ok:
            return 0

        await _mark_outcomes_synced(db_path, [r["id"] for r in rows])
        logger.info("Cloud sync pushed %d outcomes", len(rows))
        return len(rows)

    async def _sync_once(self, db_path: str) -> int:
        """Run a single sync cycle. Returns the number of cost records pushed."""
        # Outcomes first and guarded: a failure here must not prevent cost
        # records — the thing customers actually pay for — from syncing.
        try:
            await self._sync_outcomes_once(db_path)
        except Exception:
            logger.debug("Cloud sync: outcome push failed", exc_info=True)

        rows = await _fetch_unsynced(db_path, limit=_BATCH_SIZE)
        if not rows:
            return 0

        records = [_row_to_payload(r) for r in rows]
        ok = await self.push_batch(records)
        if not ok:
            return 0

        ids = [r["id"] for r in rows]
        await _mark_synced(db_path, ids)

        self.last_sync_at = datetime.now(timezone.utc)
        self.last_sync_count = len(rows)
        logger.info("Cloud sync pushed %d records", len(rows))
        return len(rows)

    async def sync_now(self, db_path: str) -> int:
        """Manual one-shot sync. Returns total records pushed."""
        total = 0
        while True:
            count = await self._sync_once(db_path)
            if count < _BATCH_SIZE:
                total += count
                break
            total += count
        return total


async def migrate_add_synced_at(db_path: str) -> None:
    """Add ``synced_at`` column to requests table if it doesn't exist.

    Safe to call multiple times -- uses PRAGMA table_info to check.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "synced_at" not in columns:
            await db.execute("ALTER TABLE requests ADD COLUMN synced_at TEXT")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_synced_at ON requests(synced_at)"
            )
            await db.commit()
            logger.info("Migration: added synced_at column to requests table")


async def get_unsynced_count(db_path: str) -> int:
    """Return the number of records that haven't been synced yet."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests WHERE synced_at IS NULL")
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _fetch_unsynced(db_path: str, limit: int) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` records that haven't been synced."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM requests WHERE synced_at IS NULL ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def _mark_synced(db_path: str, ids: list[int]) -> None:
    """Mark a batch of record IDs as synced."""
    if not ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        placeholders = ",".join("?" for _ in ids)
        await db.execute(
            f"UPDATE requests SET synced_at = ? WHERE id IN ({placeholders})",
            [now] + ids,
        )
        await db.commit()


async def _fetch_unsynced_outcomes(db_path: str, limit: int) -> list[dict[str, Any]]:
    """Fetch outcomes not yet pushed to the cloud.

    Returns [] if the table doesn't exist yet — a proxy that has never run the
    Phase B migration must not break the whole sync cycle.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM outcomes WHERE synced_at IS NULL ORDER BY id ASC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in await cursor.fetchall()]
    except aiosqlite.OperationalError:
        return []


async def _mark_outcomes_synced(db_path: str, ids: list[int]) -> None:
    if not ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        placeholders = ",".join("?" for _ in ids)
        await db.execute(
            f"UPDATE outcomes SET synced_at = ? WHERE id IN ({placeholders})",
            [now] + ids,
        )
        await db.commit()


def _outcome_row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a local outcome row to the cloud wire format."""
    metadata = row.get("metadata") or "{}"
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    return dict(
        outcome_id=row.get("outcome_id"),
        workflow_id=row.get("workflow_id"),
        status=row.get("status"),
        event_time=row.get("event_time"),
        business_value=row.get("business_value"),
        currency=row.get("currency"),
        source=row.get("source") or "cli",
        metadata=metadata,
    )


def _row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a DB row to the cloud API payload format.

    Privacy: only hashes and metadata are sent -- never raw prompt content.
    The result is then run through _sanitize_record() in push_batch().
    """
    tags = row.get("tags", "{}")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = {}

    return dict(
        timestamp=row.get("timestamp"),
        provider=row.get("provider"),
        model=row.get("model"),
        input_tokens=row.get("input_tokens", 0),
        output_tokens=row.get("output_tokens", 0),
        reasoning_tokens=row.get("reasoning_tokens", 0),
        cache_read_tokens=row.get("cache_read_tokens", 0),
        cache_write_tokens=row.get("cache_write_tokens", 0),
        cost_usd=row.get("cost_usd", 0.0),
        duration_ms=row.get("duration_ms", 0),
        status_code=row.get("status_code", 200),
        system_prompt_hash=row.get("system_prompt_hash"),
        cache_hit=row.get("cache_hit", 0),
        cache_saved_usd=row.get("cache_saved_usd", 0.0),
        tool_calls=row.get("tool_calls", 0),
        # Correlation ids for OTEL span export (never prompt content):
        trace_id=row.get("trace_id"),
        parent_span_id=row.get("parent_span_id"),
        event_id=row.get("event_id"),
        request_id=row.get("request_id"),
        # "proxy" vs scan_claude/scan_codex/...: which collector wrote the row.
        # Not prompt content and not identifying — it names the tool, not the work.
        source=row.get("source"),
        # Flattened tags, derived from CLOUD_SYNCED_TAGS so a new synced tag
        # cannot be half-wired. The backend re-nests these into `tags`.
        **{f"tag_{name}": tags.get(name) for name in CLOUD_SYNCED_TAGS},
    )
