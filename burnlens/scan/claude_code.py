"""Read Claude Code session logs from disk and convert them into RequestRecords.

Claude Code writes one ``<session-id>.jsonl`` file per session under
``~/.claude/projects/<sanitized-path>/``. The sanitized path replaces all
``/`` with ``-`` and prefixes with ``-`` (e.g. an absolute path
``/Users/me/Projects/burnlens`` becomes ``-Users-me-Projects-burnlens``).
There is no escape sequence, so a single ``-`` in the original path is
indistinguishable from a path separator on the directory name alone — for
display purposes we simply replace every ``-`` (except a leading one) with
``/``. The basename of the project is recovered from the trailing segment.

Each line of a session JSONL is one JSON object. We yield a ``RequestRecord``
for each ``type=='assistant'`` entry that carries both ``message.model`` and
``message.usage``. User messages, tool_use entries, tool_result entries, and
malformed lines are skipped.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan._common import (
    _reset_dev_identity_cache,
    resolve_dev_identity,
)
from burnlens.storage.models import RequestRecord

# Re-exported for the existing public API and for tests that import these
# names directly from ``burnlens.scan.claude_code``.
__all__ = [
    "ClaudeSession",
    "ScanResult",
    "decode_project_path",
    "discover_sessions",
    "parse_session",
    "resolve_dev_identity",
    "scan_claude_code",
]

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass
class ClaudeSession:
    """One Claude Code session file on disk."""

    session_id: str
    project_path: str
    project_basename: str
    file_path: Path
    modified_at: datetime


def decode_project_path(sanitized: str) -> str:
    """Reverse Claude Code's path-to-dirname sanitization.

    Claude Code replaces ``/`` with ``-`` and keeps the leading slash as a
    leading dash. We restore the leading slash and convert remaining dashes
    to slashes. This is lossy for paths containing real dashes, but matches
    the convention used by Claude Code itself when generating these dirs.
    """
    if not sanitized:
        return ""
    if sanitized.startswith("-"):
        return "/" + sanitized[1:].replace("-", "/")
    return sanitized.replace("-", "/")


def discover_sessions(
    since: datetime | None = None,
    project_filter: str | None = None,
    projects_dir: Path | None = None,
) -> list[ClaudeSession]:
    """Walk ``~/.claude/projects/`` and return matching session files.

    - ``since``: only sessions whose mtime is at or after this timestamp.
    - ``project_filter``: substring match against the project basename.
    - ``projects_dir``: override for tests.
    """
    root = projects_dir if projects_dir is not None else CLAUDE_PROJECTS_DIR
    if not root.exists():
        return []

    sessions: list[ClaudeSession] = []
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        sanitized = project_dir.name
        decoded = decode_project_path(sanitized)
        basename = decoded.rsplit("/", 1)[-1] or sanitized.lstrip("-")

        if project_filter and project_filter not in basename:
            continue

        for jsonl in sorted(project_dir.glob("*.jsonl")):
            # Skip vendor sub-directories and helper files
            try:
                stat = jsonl.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if since is not None and mtime < since:
                continue

            sessions.append(
                ClaudeSession(
                    session_id=jsonl.stem,
                    project_path=decoded,
                    project_basename=basename,
                    file_path=jsonl,
                    modified_at=mtime,
                )
            )
    return sessions


def _parse_timestamp(raw: str | None) -> datetime:
    """Parse Claude Code's ISO 8601 timestamp (``...Z``) to a tz-aware datetime."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        # Python <3.11 fromisoformat doesn't accept trailing Z.
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def parse_session(session: ClaudeSession) -> Iterator[RequestRecord]:
    """Yield one RequestRecord per assistant message with model + usage.

    Skips: user messages, tool_use / tool_result entries, malformed JSON lines,
    and assistant entries missing a model or usage block. Cost is calculated
    via the existing ``cost.calculator.calculate_cost`` function.
    """
    try:
        fh = session.file_path.open("r", encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot open session %s: %s", session.file_path, exc)
        return

    dev = resolve_dev_identity(session.project_path)

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
            if entry.get("type") != "assistant":
                continue

            message = entry.get("message")
            if not isinstance(message, dict):
                continue

            model = message.get("model")
            usage_raw = message.get("usage")
            if not model or not isinstance(usage_raw, dict):
                continue
            # Claude Code emits "<synthetic>" entries for internal/replayed
            # turns that did not hit the API. Skip them — no real cost.
            if model == "<synthetic>":
                continue

            request_id = message.get("id")
            if not request_id:
                # Without a stable id we cannot dedup safely, so skip.
                continue

            usage = TokenUsage(
                input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
                output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
                cache_read_tokens=int(usage_raw.get("cache_read_input_tokens", 0) or 0),
                cache_write_tokens=int(
                    usage_raw.get("cache_creation_input_tokens", 0) or 0
                ),
            )

            cost = calculate_cost("anthropic", model, usage)
            ts = _parse_timestamp(entry.get("timestamp"))

            tags = {
                "repo": session.project_basename,
                "dev": dev,
                "session": session.session_id,
            }

            yield RequestRecord(
                provider="anthropic",
                model=model,
                request_path="/v1/messages",
                timestamp=ts,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=0,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cost_usd=cost,
                duration_ms=0.0,
                status_code=200,
                tags=tags,
                source="scan_claude",
                request_id=str(request_id),
            )


@dataclass
class ScanResult:
    """Outcome of a scan run, used by the CLI to render a summary."""

    sessions_found: int = 0
    messages_parsed: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    total_cost_usd: float = 0.0
    cost_by_project: dict[str, float] = None  # type: ignore[assignment]
    messages_by_project: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.cost_by_project is None:
            self.cost_by_project = {}
        if self.messages_by_project is None:
            self.messages_by_project = {}


async def scan_claude_code(
    db_path: str,
    since: datetime | None = None,
    project_filter: str | None = None,
    dry_run: bool = False,
    projects_dir: Path | None = None,
) -> ScanResult:
    """Scan Claude Code sessions and import them into the requests DB.

    Idempotent: re-runs hit the partial unique index on (source, request_id)
    and silently skip already-imported messages. Returns a ScanResult that
    summarizes counts and cost totals for CLI rendering.
    """
    from burnlens.storage.database import insert_request

    _reset_dev_identity_cache()
    result = ScanResult()

    sessions = discover_sessions(
        since=since,
        project_filter=project_filter,
        projects_dir=projects_dir,
    )
    result.sessions_found = len(sessions)

    for session in sessions:
        for record in parse_session(session):
            result.messages_parsed += 1
            result.total_cost_usd += record.cost_usd
            result.cost_by_project[session.project_basename] = (
                result.cost_by_project.get(session.project_basename, 0.0)
                + record.cost_usd
            )
            result.messages_by_project[session.project_basename] = (
                result.messages_by_project.get(session.project_basename, 0) + 1
            )

            if dry_run:
                continue

            row_id = await insert_request(db_path, record)
            if row_id > 0:
                result.records_inserted += 1
            else:
                result.records_skipped += 1

    return result
