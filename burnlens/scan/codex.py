"""Read Codex (OpenAI) session logs from disk and convert them into RequestRecords.

Codex writes session data as JSONL files under:
  ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl

Override: $CODEX_HOME changes the base directory.

Within each file, token usage lives in ``event_msg`` events where
``payload.type == "token_count"`` and ``payload.info`` is non-null.
Per-call counts are under ``payload.info.last_token_usage``; cumulative
totals under ``payload.info.total_token_usage`` are skipped to avoid
double-counting.  The active model comes from the last-seen ``turn_context``
event's ``payload.model``.  The working directory comes from the
``session_meta`` event's ``payload.cwd``.

Real schema verified 2026-05-03 against ~/.codex/sessions on macOS
(Codex 0.102.0-alpha.2, model gpt-5.2-codex).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan._common import _reset_dev_identity_cache, resolve_dev_identity
from burnlens.storage.models import RequestRecord

logger = logging.getLogger(__name__)


def codex_sessions_dir() -> Path:
    """Return the root sessions directory, honouring ``$CODEX_HOME``."""
    base = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    return Path(base) / "sessions"


@dataclass
class CodexSession:
    """One Codex session file on disk."""

    session_id: str       # filename stem minus "rollout-" prefix
    file_path: Path
    date: date            # from YYYY/MM/DD directory structure
    cwd: str | None = None  # populated lazily from session_meta during parse


def discover_sessions(
    since: datetime | None = None,
    sessions_dir: Path | None = None,
) -> list[CodexSession]:
    """Walk YYYY/MM/DD structure under ``codex_sessions_dir()``.

    Filters by file mtime when ``since`` is given. Returns sessions sorted
    by date ascending. Pass ``sessions_dir`` to override the default location
    (used by tests).
    """
    root = sessions_dir if sessions_dir is not None else codex_sessions_dir()
    if not root.exists():
        return []

    sessions: list[CodexSession] = []

    for year_dir in sorted(root.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue

                try:
                    session_date = date(
                        int(year_dir.name),
                        int(month_dir.name),
                        int(day_dir.name),
                    )
                except ValueError:
                    continue

                for jsonl in sorted(day_dir.glob("rollout-*.jsonl")):
                    try:
                        stat = jsonl.stat()
                    except OSError:
                        continue
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    if since is not None and mtime < since:
                        continue

                    stem = jsonl.stem  # e.g. rollout-2026-01-27T21-59-05-<uuid>
                    session_id = stem[len("rollout-"):] if stem.startswith("rollout-") else stem

                    sessions.append(
                        CodexSession(
                            session_id=session_id,
                            file_path=jsonl,
                            date=session_date,
                        )
                    )

    return sessions


def _parse_timestamp(raw: str | None) -> datetime:
    """Parse Codex ISO 8601 timestamp to a tz-aware datetime."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def parse_session(session: CodexSession) -> Iterator[RequestRecord]:
    """Yield one RequestRecord per billable token_count event in a session file.

    State tracked while reading:
      - ``session_cwd``: from the first ``session_meta`` event
      - ``current_model``: from the most recent ``turn_context`` event
      - ``tc_ordinal``: 0-indexed position of ALL token_count events seen
        (including null-info rate-limit-only events), used to form stable
        ``request_id`` values for dedup.

    Skips:
      - Non-token_count events (function_call, message, reasoning, …)
      - token_count events where ``payload.info`` is null (rate-limit ticks)
      - token_count events with zero total tokens
      - Malformed JSON lines (logged at DEBUG)
    """
    try:
        fh = session.file_path.open("r", encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot open Codex session %s: %s", session.file_path, exc)
        return

    session_cwd: str | None = None
    current_model: str | None = None
    tc_ordinal: int = 0

    with fh:
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

            event_type = entry.get("type", "")
            payload = entry.get("payload") or {}

            if event_type == "session_meta" and session_cwd is None:
                # Extract working directory from the session header.
                session_cwd = payload.get("cwd") or None

            elif event_type == "turn_context":
                # Track the most recent model in use.
                model = payload.get("model")
                if model:
                    current_model = model

            elif event_type == "event_msg" and payload.get("type") == "token_count":
                ordinal = tc_ordinal
                tc_ordinal += 1

                info = payload.get("info")
                if not info or not isinstance(info, dict):
                    # Rate-limit-only tick, no per-call usage.
                    continue

                last = info.get("last_token_usage") or {}
                if not isinstance(last, dict):
                    continue

                in_tok = int(last.get("input_tokens", 0) or 0)
                out_tok = int(last.get("output_tokens", 0) or 0)
                cache_read = int(last.get("cached_input_tokens", 0) or 0)
                reasoning = int(last.get("reasoning_output_tokens", 0) or 0)

                if in_tok + out_tok + reasoning == 0:
                    continue

                if current_model is None:
                    logger.debug(
                        "token_count at ordinal %d in %s has no preceding turn_context — skipping",
                        ordinal,
                        session.file_path,
                    )
                    continue

                cwd = session_cwd or os.getcwd()
                dev = resolve_dev_identity(cwd)
                tag_repo: str | None = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else None

                usage = TokenUsage(
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    reasoning_tokens=reasoning,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=0,
                )
                cost = calculate_cost("openai", current_model, usage)
                ts = _parse_timestamp(entry.get("timestamp"))

                tags: dict[str, str] = {"dev": dev, "session": session.session_id}
                if tag_repo:
                    tags["repo"] = tag_repo

                yield RequestRecord(
                    provider="openai",
                    model=current_model,
                    request_path="/codex/session",
                    timestamp=ts,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    reasoning_tokens=reasoning,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=0,
                    cost_usd=cost,
                    duration_ms=0.0,
                    status_code=200,
                    tags=tags,
                    source="scan_codex",
                    request_id=f"{session.session_id}:{ordinal}",
                )


@dataclass
class CodexScanResult:
    """Outcome of a Codex scan run, used by the CLI to render a summary."""

    sessions_found: int = 0
    events_parsed: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    total_cost_usd: float = 0.0
    cost_by_model: dict[str, float] = None  # type: ignore[assignment]
    events_by_model: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.cost_by_model is None:
            self.cost_by_model = {}
        if self.events_by_model is None:
            self.events_by_model = {}


async def scan_codex(
    db_path: str,
    since: datetime | None = None,
    dry_run: bool = False,
    sessions_dir: Path | None = None,
) -> CodexScanResult:
    """Scan Codex session files and import them into the requests DB.

    Idempotent: re-runs hit the partial unique index on (source, request_id)
    and silently skip already-imported events. Returns a CodexScanResult
    that summarises counts and cost totals for CLI rendering.

    Args:
        db_path: BurnLens SQLite DB to insert into.
        since: only import sessions modified at/after this datetime.
        dry_run: parse but don't insert.
        sessions_dir: override sessions directory (used by tests).
    """
    from burnlens.storage.database import insert_request

    _reset_dev_identity_cache()
    result = CodexScanResult()

    sessions = discover_sessions(since=since, sessions_dir=sessions_dir)
    result.sessions_found = len(sessions)

    for session in sessions:
        for record in parse_session(session):
            result.events_parsed += 1
            result.total_cost_usd += record.cost_usd
            result.cost_by_model[record.model] = (
                result.cost_by_model.get(record.model, 0.0) + record.cost_usd
            )
            result.events_by_model[record.model] = (
                result.events_by_model.get(record.model, 0) + 1
            )

            if dry_run:
                continue

            row_id = await insert_request(db_path, record)
            if row_id > 0:
                result.records_inserted += 1
            else:
                result.records_skipped += 1

    return result
