"""Read Cursor session data from disk and convert it into RequestRecords.

Cursor stores session state in a single SQLite database at:

  - macOS:   ``~/Library/Application Support/Cursor/User/globalStorage/state.vscdb``
  - Linux:   ``~/.config/Cursor/User/globalStorage/state.vscdb``
  - Windows: ``%APPDATA%/Cursor/User/globalStorage/state.vscdb``

The relevant table is ``cursorDiskKV (key TEXT UNIQUE, value BLOB)``. Per
CodeBurn's reverse engineering, conversation bubbles are stored as rows
where ``key`` matches ``bubbleId:%`` and ``value`` is a JSON blob with token
counts under ``tokenCount.{inputTokens,outputTokens,cacheReadTokens,
cacheWriteTokens}``, plus ``model``, ``timestamp``, and ``conversationId``.

**Schema verification note (2026-05-03):** verified table layout
``cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)`` against a
fresh Cursor install on macOS. Empty install holds only ``composerData:%``
shells and one ``composerVirtualRowHeights:_recentIds`` row — no
``bubbleId:%`` rows yet. Modern Cursor may also nest conversation data
inside ``composerData.conversationMap`` / a ``bubbleDataMap`` capability;
we only read top-level ``bubbleId:%`` rows for now (matches the spec) and
will revisit if usage data turns out to live elsewhere on a populated DB.

Cursor's "Auto" mode hides the underlying model name. We relabel any bubble
whose model is ``"auto"`` (case-insensitive) as ``"cursor-auto-sonnet-est"``
so the dashboard makes the estimate explicit, and the cost calculator
routes those bubbles to current Sonnet pricing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import aiosqlite

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan._common import _reset_dev_identity_cache, resolve_dev_identity
from burnlens.storage.models import RequestRecord

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".burnlens" / "cache"
CACHE_FILE = CACHE_DIR / "cursor_parsed.json"

# Marker for Cursor's hidden 'Auto' model. Surfaces in the dashboard and
# routes to current Sonnet pricing in burnlens.cost.calculator.
AUTO_MODEL_LABEL = "cursor-auto-sonnet-est"


# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------


def cursor_db_path() -> Path | None:
    """Return platform-specific path to Cursor's ``state.vscdb``, or None.

    Returns None if Cursor isn't installed (file doesn't exist) so callers
    can skip gracefully without raising.
    """
    if sys.platform == "darwin":
        path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    elif sys.platform.startswith("linux"):
        path = Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        path = Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    else:
        return None

    return path if path.exists() else None


# ---------------------------------------------------------------------------
# Bubble parsing
# ---------------------------------------------------------------------------


@dataclass
class CursorBubble:
    """One Cursor conversation bubble that carried token usage."""

    bubble_id: str
    conversation_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    timestamp: datetime
    workspace_path: str | None = None


def _parse_timestamp(raw: int | float | str | None) -> datetime:
    """Best-effort timestamp parse. Cursor uses unix-ms ints in some shapes
    and ISO strings in others. Falls back to ``now()`` if unparseable.
    """
    if raw is None:
        return datetime.now(timezone.utc)
    if isinstance(raw, (int, float)):
        # Heuristic: > 1e12 → milliseconds; otherwise seconds.
        seconds = raw / 1000.0 if raw > 1_000_000_000_000 else float(raw)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return datetime.now(timezone.utc)
    if isinstance(raw, str):
        try:
            normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
            return datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _normalize_model(model: str | None) -> str:
    """Relabel Cursor's 'Auto' marker to the explicit estimate label."""
    if not model:
        return AUTO_MODEL_LABEL
    if model.strip().lower() == "auto":
        return AUTO_MODEL_LABEL
    return model


def _bubble_from_row(key: str, value_raw: bytes | str | None) -> CursorBubble | None:
    """Parse one ``cursorDiskKV`` row into a CursorBubble, or None to skip."""
    if value_raw is None:
        return None
    if isinstance(value_raw, bytes):
        try:
            value_str = value_raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — defensive
            return None
    else:
        value_str = value_raw

    try:
        data = json.loads(value_str)
    except json.JSONDecodeError as exc:
        logger.debug("Skipping malformed Cursor bubble JSON for %s: %s", key, exc)
        return None
    if not isinstance(data, dict):
        return None

    token_count = data.get("tokenCount") or {}
    if not isinstance(token_count, dict):
        return None

    in_tok = int(token_count.get("inputTokens", 0) or 0)
    out_tok = int(token_count.get("outputTokens", 0) or 0)
    cache_read = int(token_count.get("cacheReadTokens", 0) or 0)
    cache_write = int(token_count.get("cacheWriteTokens", 0) or 0)
    if in_tok + out_tok + cache_read + cache_write == 0:
        return None  # nothing to bill

    bubble_id = key.split(":", 1)[1] if key.startswith("bubbleId:") else key
    workspace = data.get("workspacePath") or data.get("workspace") or None

    return CursorBubble(
        bubble_id=bubble_id,
        conversation_id=str(data.get("conversationId") or ""),
        model=_normalize_model(data.get("model")),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        timestamp=_parse_timestamp(data.get("timestamp")),
        workspace_path=workspace,
    )


async def read_bubbles(
    db_path: Path,
    since: datetime | None = None,
) -> list[CursorBubble]:
    """Read all bubbles from a Cursor SQLite DB. Returns a list (not iterator).

    Opens the DB read-only via the ``file:...?mode=ro`` URI so we never write
    to the user's running Cursor session. Handles ``SQLITE_BUSY`` (DB locked
    by Cursor) with one retry after 1s, then logs and returns ``[]``.
    """
    uri = f"file:{db_path}?mode=ro"
    bubbles: list[CursorBubble] = []

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            async with aiosqlite.connect(uri, uri=True) as db:
                cursor = await db.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
                )
                rows = await cursor.fetchall()
                for key, value in rows:
                    bubble = _bubble_from_row(key, value)
                    if bubble is None:
                        continue
                    if since is not None and bubble.timestamp < since:
                        continue
                    bubbles.append(bubble)
            return bubbles
        except aiosqlite.OperationalError as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "locked" in msg or "busy" in msg:
                if attempt == 0:
                    logger.debug("Cursor DB locked, retrying in 1s")
                    await asyncio.sleep(1.0)
                    continue
                logger.warning(
                    "Cursor DB still locked after retry — skipping scan: %s", exc
                )
                return []
            # Non-busy operational error (e.g. malformed DB) — log and bail
            logger.warning("Cannot read Cursor DB %s: %s", db_path, exc)
            return []

    if last_exc is not None:
        logger.warning("Cursor DB read failed: %s", last_exc)
    return bubbles


# ---------------------------------------------------------------------------
# Bubble → RequestRecord
# ---------------------------------------------------------------------------


def bubble_to_record(bubble: CursorBubble) -> RequestRecord:
    """Convert a CursorBubble to a RequestRecord ready for ``insert_request``."""
    workspace = bubble.workspace_path or ""
    if workspace:
        repo_basename: str | None = workspace.rstrip("/").rsplit("/", 1)[-1] or None
    else:
        repo_basename = None

    dev = resolve_dev_identity(workspace) if workspace else resolve_dev_identity(os.getcwd())

    usage = TokenUsage(
        input_tokens=bubble.input_tokens,
        output_tokens=bubble.output_tokens,
        cache_read_tokens=bubble.cache_read_tokens,
        cache_write_tokens=bubble.cache_write_tokens,
    )
    cost = calculate_cost("cursor", bubble.model, usage)

    tags: dict[str, str] = {"dev": dev, "session": bubble.conversation_id}
    if repo_basename:
        tags["repo"] = repo_basename

    return RequestRecord(
        provider="cursor",
        model=bubble.model,
        request_path="/cursor/bubble",
        timestamp=bubble.timestamp,
        input_tokens=bubble.input_tokens,
        output_tokens=bubble.output_tokens,
        reasoning_tokens=0,
        cache_read_tokens=bubble.cache_read_tokens,
        cache_write_tokens=bubble.cache_write_tokens,
        cost_usd=cost,
        duration_ms=0.0,
        status_code=200,
        tags=tags,
        source="scan_cursor",
        request_id=bubble.bubble_id,
    )


# ---------------------------------------------------------------------------
# Result + cache
# ---------------------------------------------------------------------------


@dataclass
class CursorScanResult:
    """Outcome of a Cursor scan run, used by the CLI to render a summary."""

    db_path: Path | None = None
    db_size_bytes: int = 0
    db_mtime: float = 0.0
    skipped_due_to_cache: bool = False
    bubbles_parsed: int = 0
    conversations_seen: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    total_cost_usd: float = 0.0
    auto_mode_bubbles: int = 0


def _read_cache() -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Cursor cache read failed: %s", exc)
    return None


def _write_cache(payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError as exc:
        logger.debug("Cursor cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public scan entry point
# ---------------------------------------------------------------------------


async def scan_cursor(
    db_path: str,
    since: datetime | None = None,
    dry_run: bool = False,
    cursor_db: Path | None = None,
    use_cache: bool = True,
) -> CursorScanResult:
    """Scan Cursor's ``state.vscdb`` and import bubbles into the requests DB.

    Idempotent: re-runs hit the partial unique index ``idx_scan_dedup`` on
    ``(source, request_id)`` and silently skip already-imported bubbles.

    A small JSON cache at ``~/.burnlens/cache/cursor_parsed.json`` records
    the DB's mtime + size from the last successful scan so unchanged DBs
    can short-circuit without a SQLite roundtrip.

    Args:
        db_path: BurnLens SQLite DB to insert into.
        since: only import bubbles with timestamps at/after this datetime.
        dry_run: parse but don't insert; still updates the cache.
        cursor_db: override Cursor DB location (used by tests).
        use_cache: short-circuit when DB mtime+size matches the cache.

    Returns:
        CursorScanResult summarizing parsed/inserted counts and cost.
    """
    from burnlens.storage.database import insert_request

    _reset_dev_identity_cache()
    result = CursorScanResult()

    src_db = cursor_db if cursor_db is not None else cursor_db_path()
    if src_db is None or not src_db.exists():
        return result

    try:
        stat = src_db.stat()
    except OSError as exc:
        logger.warning("Cannot stat Cursor DB %s: %s", src_db, exc)
        return result

    result.db_path = src_db
    result.db_size_bytes = stat.st_size
    result.db_mtime = stat.st_mtime

    if use_cache:
        cache = _read_cache()
        if (
            cache
            and cache.get("db_path") == str(src_db)
            and cache.get("db_size") == stat.st_size
            and cache.get("db_mtime") == stat.st_mtime
        ):
            result.skipped_due_to_cache = True
            return result

    bubbles = await read_bubbles(src_db, since=since)
    result.bubbles_parsed = len(bubbles)
    result.conversations_seen = len({b.conversation_id for b in bubbles if b.conversation_id})
    result.auto_mode_bubbles = sum(1 for b in bubbles if b.model == AUTO_MODEL_LABEL)

    for bubble in bubbles:
        record = bubble_to_record(bubble)
        result.total_cost_usd += record.cost_usd

        if dry_run:
            continue

        row_id = await insert_request(db_path, record)
        if row_id > 0:
            result.records_inserted += 1
        else:
            result.records_skipped += 1

    if not dry_run:
        _write_cache(
            {
                "db_path": str(src_db),
                "db_size": stat.st_size,
                "db_mtime": stat.st_mtime,
                "scanned_at": time.time(),
                "bubbles_parsed": result.bubbles_parsed,
            }
        )

    return result


def _reset_cursor_cache() -> None:
    """Test helper — remove the on-disk cache file if present."""
    try:
        CACHE_FILE.unlink()
    except FileNotFoundError:
        pass
