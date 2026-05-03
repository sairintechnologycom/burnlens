"""Read Gemini CLI session logs from disk and convert them into RequestRecords.

VERIFIED AGAINST: real ~/.gemini/ on macOS (Gemini CLI, observed 2026-05-03).

Real schema differs significantly from the documented spec:
  Location:    ~/.gemini/tmp/<project-slug>/chats/  (NOT ~/.gemini/sessions/)
  Formats (both may coexist across CLI versions):
    session-*.json   older format — single JSON object with a messages[] array
    session-*.jsonl  newer format — append-only JSONL: session header on line 1,
                     then one event per line (gemini/user messages, $set mutations)
  Token fields:
    tokens.input    → input_tokens (promptTokenCount equivalent)
    tokens.output   → output_tokens (candidatesTokenCount equivalent)
    tokens.cached   → cache_read_tokens (cachedContentTokenCount equivalent)
    tokens.thoughts → reasoning_tokens (thoughtsTokenCount, Gemini 2.5 thinking)
    tokens.tool     → ignored (tool call token overhead, not separately billable)
  Message type: "gemini" (not "assistant")
  CWD source:   ~/.gemini/tmp/<project>/.project_root (file contains abs path)

Models observed on this machine (2026-05-03):
  gemini-3-flash-preview   (5396 turns)
  gemini-3.1-pro-preview   (293 turns)
  NOTE: Neither is in pricing_data/google.json yet. Scan will report $0 cost
  and emit one warning per missing model per run. Add entries to google.json
  once official pricing is published.

TODO (older format): UUID subdirs exist inside chats/ (e.g., chats/<uuid>/...);
their contents are planning artifacts, not session logs — safely ignored for now.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan._common import _reset_dev_identity_cache, resolve_dev_identity
from burnlens.storage.models import RequestRecord

logger = logging.getLogger(__name__)

GEMINI_HOME_ENV = "GEMINI_HOME"

GEMINI_PROBE_PATHS = [
    Path.home() / ".gemini",
    Path.home() / ".config" / "gemini-cli",
    Path.home() / "Library" / "Application Support" / "Gemini",
]


def gemini_sessions_dir() -> Path | None:
    """Return the Gemini CLI home directory, or None if not found.

    Honors $GEMINI_HOME. Returns the base dir (e.g. ~/.gemini); sessions live
    under <base>/tmp/<project-slug>/chats/.
    """
    env = os.environ.get(GEMINI_HOME_ENV)
    if env:
        p = Path(env)
        if p.exists():
            return p

    for probe in GEMINI_PROBE_PATHS:
        if probe.exists():
            return probe

    return None


@dataclass
class GeminiSession:
    """One Gemini CLI session file on disk."""

    session_id: str        # file stem (e.g. session-2026-04-19T05-21-52bcf9b0)
    project_slug: str      # directory name under <gemini_home>/tmp/
    file_path: Path
    modified_at: datetime
    cwd: str | None        # from .project_root; None if unavailable


def _read_project_root(project_dir: Path) -> str | None:
    """Return the project's working directory from its .project_root file."""
    pr = project_dir / ".project_root"
    try:
        content = pr.read_text(encoding="utf-8").strip()
        return content or None
    except OSError:
        return None


def discover_sessions(
    since: datetime | None = None,
    gemini_dir: Path | None = None,
) -> list[GeminiSession]:
    """Walk <gemini_home>/tmp/<project>/chats/ for session files.

    Returns an empty list if the Gemini home dir is absent or has no sessions.
    Filters by mtime when ``since`` is given. Pass ``gemini_dir`` to override
    the default home location (used by tests).
    """
    base = gemini_dir if gemini_dir is not None else gemini_sessions_dir()
    if base is None:
        return []

    tmp_dir = base / "tmp"
    if not tmp_dir.exists():
        return []

    sessions: list[GeminiSession] = []

    for project_dir in sorted(tmp_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        chats_dir = project_dir / "chats"
        if not chats_dir.is_dir():
            continue

        cwd = _read_project_root(project_dir)
        slug = project_dir.name

        # Collect both JSON (older) and JSONL (newer) session files.
        session_files: list[Path] = sorted(
            list(chats_dir.glob("session-*.json"))
            + list(chats_dir.glob("session-*.jsonl"))
        )

        for sf in session_files:
            try:
                stat = sf.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if since is not None and mtime < since:
                continue

            sessions.append(
                GeminiSession(
                    session_id=sf.stem,
                    project_slug=slug,
                    file_path=sf,
                    modified_at=mtime,
                    cwd=cwd,
                )
            )

    return sessions


def _parse_timestamp(raw: str | None) -> datetime:
    """Parse Gemini CLI's ISO 8601 timestamp to a tz-aware datetime."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def _record_from_gemini_message(
    msg: dict,
    session: GeminiSession,
    turn_ordinal: int,
    dev: str,
    tag_repo: str | None,
    warned_models: set[str],
) -> RequestRecord | None:
    """Build a RequestRecord from a single gemini-type message dict.

    Returns None if the message lacks usable token data.
    """
    tokens_raw = msg.get("tokens")
    if not isinstance(tokens_raw, dict):
        return None

    model = msg.get("model") or ""
    if not model:
        return None

    in_tok = int(tokens_raw.get("input", 0) or 0)
    out_tok = int(tokens_raw.get("output", 0) or 0)
    cached = int(tokens_raw.get("cached", 0) or 0)
    thoughts = int(tokens_raw.get("thoughts", 0) or 0)

    if in_tok + out_tok + thoughts == 0:
        return None

    usage = TokenUsage(
        input_tokens=in_tok,
        output_tokens=out_tok,
        reasoning_tokens=thoughts,
        cache_read_tokens=cached,
        cache_write_tokens=0,
    )

    # Skip calculate_cost for models already known to be missing from the
    # pricing DB — prevents pricing.py from emitting O(n) repeated warnings.
    if model in warned_models:
        cost = 0.0
    else:
        cost = calculate_cost("google", model, usage)
        if cost == 0.0:
            logger.warning(
                "Model not in pricing DB: %r. Add to pricing_data/google.json. "
                "(cost recorded as $0.00)",
                model,
            )
            warned_models.add(model)

    ts = _parse_timestamp(msg.get("timestamp"))
    message_id = msg.get("id") or str(turn_ordinal)
    request_id = f"{session.session_id}:{message_id}"

    tags: dict[str, str] = {"dev": dev, "session": session.session_id}
    if tag_repo:
        tags["repo"] = tag_repo

    return RequestRecord(
        provider="google",
        model=model,
        request_path="/gemini/session",
        timestamp=ts,
        input_tokens=in_tok,
        output_tokens=out_tok,
        reasoning_tokens=thoughts,
        cache_read_tokens=cached,
        cache_write_tokens=0,
        cost_usd=cost,
        duration_ms=0.0,
        status_code=200,
        tags=tags,
        source="scan_gemini",
        request_id=request_id,
    )


def parse_session(
    session: GeminiSession,
    warned_models: set[str] | None = None,
) -> Iterator[RequestRecord]:
    """Yield one RequestRecord per billable gemini message in a session file.

    Handles both JSON and JSONL formats transparently based on file extension.
    Skips malformed lines (logged at DEBUG), $set mutation events, user
    messages, and gemini messages without token data.

    Pass a shared ``warned_models`` set across multiple ``parse_session`` calls
    (e.g. inside ``scan_gemini_cli``) to ensure each missing-pricing warning is
    emitted exactly once per scan run rather than once per session.
    """
    try:
        fh = session.file_path.open("r", encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot open Gemini session %s: %s", session.file_path, exc)
        return

    cwd = session.cwd or os.getcwd()
    dev = resolve_dev_identity(cwd)
    tag_repo: str | None = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else None
    _warned = warned_models if warned_models is not None else set()

    is_jsonl = session.file_path.suffix == ".jsonl"

    with fh:
        if is_jsonl:
            yield from _parse_jsonl(fh, session, dev, tag_repo, _warned)
        else:
            yield from _parse_json(fh, session, dev, tag_repo, _warned)


def _parse_json(
    fh,
    session: GeminiSession,
    dev: str,
    tag_repo: str | None,
    warned_models: set[str],
) -> Iterator[RequestRecord]:
    """Parse older single-JSON-object session files."""
    try:
        data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Malformed JSON session %s: %s", session.file_path, exc)
        return

    if not isinstance(data, dict):
        return

    messages = data.get("messages") or []
    for ordinal, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "gemini":
            continue
        record = _record_from_gemini_message(
            msg, session, ordinal, dev, tag_repo, warned_models
        )
        if record is not None:
            yield record


def _parse_jsonl(
    fh,
    session: GeminiSession,
    dev: str,
    tag_repo: str | None,
    warned_models: set[str],
) -> Iterator[RequestRecord]:
    """Parse newer append-only JSONL session files."""
    ordinal = 0
    for line_no, raw_line in enumerate(fh, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug(
                "Skipping malformed JSONL line %s:%d: %s",
                session.file_path,
                line_no,
                exc,
            )
            continue

        if not isinstance(entry, dict):
            continue

        # Skip $set mutation events (e.g. {"$set": {"lastUpdated": "..."}})
        if "$set" in entry:
            continue

        # Skip session header (has sessionId but no type) and user messages
        if entry.get("type") != "gemini":
            continue

        record = _record_from_gemini_message(
            entry, session, ordinal, dev, tag_repo, warned_models
        )
        if record is not None:
            ordinal += 1
            yield record


@dataclass
class GeminiScanResult:
    """Outcome of a Gemini CLI scan run, used by the CLI to render a summary."""

    sessions_found: int = 0
    turns_parsed: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    total_cost_usd: float = 0.0
    cost_by_model: dict[str, float] = None  # type: ignore[assignment]
    turns_by_model: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.cost_by_model is None:
            self.cost_by_model = {}
        if self.turns_by_model is None:
            self.turns_by_model = {}


async def scan_gemini_cli(
    db_path: str,
    since: datetime | None = None,
    dry_run: bool = False,
    gemini_dir: Path | None = None,
) -> GeminiScanResult:
    """Scan Gemini CLI session files and import them into the requests DB.

    Idempotent: re-runs hit the partial unique index on (source, request_id)
    and silently skip already-imported turns. Returns a GeminiScanResult that
    summarises counts and cost totals for CLI rendering.

    Args:
        db_path: BurnLens SQLite DB to insert into.
        since: only import sessions modified at/after this datetime.
        dry_run: parse but don't insert.
        gemini_dir: override the Gemini home directory (used by tests).
    """
    from burnlens.storage.database import insert_request

    _reset_dev_identity_cache()
    result = GeminiScanResult()

    sessions = discover_sessions(since=since, gemini_dir=gemini_dir)
    result.sessions_found = len(sessions)

    # Shared across all sessions so each missing-model warning fires exactly once.
    warned_models: set[str] = set()

    for session in sessions:
        for record in parse_session(session, warned_models=warned_models):
            result.turns_parsed += 1
            result.total_cost_usd += record.cost_usd
            result.cost_by_model[record.model] = (
                result.cost_by_model.get(record.model, 0.0) + record.cost_usd
            )
            result.turns_by_model[record.model] = (
                result.turns_by_model.get(record.model, 0) + 1
            )

            if dry_run:
                continue

            row_id = await insert_request(db_path, record)
            if row_id > 0:
                result.records_inserted += 1
            else:
                result.records_skipped += 1

    return result
