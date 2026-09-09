"""Economics-graph Phase C: outcomes BurnLens derives instead of being told.

Unit-economics products usually die on instrumentation. Cost-per-outcome needs
someone to report outcomes, and nobody does — so the feature ships, nobody wires
it up, and the dashboard stays empty forever.

For coding agents that instrumentation already exists, in git. A merged pull
request *is* an accepted outcome; a closed-unmerged one is a rejected outcome.
This reads them from GitHub and writes them into the same `outcomes` table the
API path writes to, so "cost per merged PR" works with nothing to integrate.

The join back to spend is `workflow_id`, which both sides get from
:func:`burnlens.scan._common.repo_workflow_id` — never spelled out here, because
two hand-written copies of a join key is how a dashboard silently reads zero.

Cost is attributed at repository granularity, not per-PR: agent session logs
record which repo a session was in, not which branch or PR. So the number is
"total agent spend on this repo / PRs merged", which is the honest reading of
what one merged PR costs when several are in flight at once.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from burnlens.scan._common import repo_workflow_id

logger = logging.getLogger(__name__)

# gh can be slow on large repos; the CLI surfaces this rather than hanging.
_GH_TIMEOUT_SECONDS = 60

GH_MISSING_MESSAGE = (
    "the GitHub CLI (gh) is not installed. Install it from https://cli.github.com "
    "and run `gh auth login`."
)


class DeriveError(RuntimeError):
    """Raised when outcomes cannot be derived, with a message worth showing."""


def gh_available() -> bool:
    """True when the GitHub CLI is on PATH. Presence only — not authenticated."""
    return shutil.which("gh") is not None


@dataclass
class DeriveResult:
    """What a derive run did, for the CLI to report honestly."""

    repo: str | None = None
    workflow_id: str | None = None
    pull_requests_seen: int = 0
    accepted: int = 0
    rejected: int = 0
    skipped_open: int = 0
    inserted: int = 0
    corrected: int = 0
    duplicates: int = 0
    scope_since: str | None = None
    scope_until: str | None = None
    import_complete: bool = True


def _run_gh(repo_path: str, *args: str) -> str:
    """Run a gh command in ``repo_path`` and return stdout.

    Raises DeriveError with an actionable message rather than leaking a
    CalledProcessError — this runs from a CLI a human is watching.
    """
    if not gh_available():
        raise DeriveError(GH_MISSING_MESSAGE)
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DeriveError(f"gh timed out after {_GH_TIMEOUT_SECONDS}s")
    except OSError as exc:
        raise DeriveError(f"could not run gh: {exc}")

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "authentication" in stderr.lower() or "gh auth login" in stderr:
            raise DeriveError(f"gh is not authenticated — run `gh auth login`. ({stderr})")
        raise DeriveError(f"gh failed: {stderr or 'unknown error'}")
    return result.stdout


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # gh emits RFC3339 with a trailing Z, which fromisoformat rejects
        # before 3.11.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _local_repo_name(repo_path: str) -> str | None:
    """Repository name as the scanners see it — the working tree's directory.

    Deliberately NOT the GitHub name: session logs are keyed by local directory,
    so using the remote's name here would break the join whenever a checkout is
    renamed or forked.
    """
    from burnlens.git_context import read_git_context

    return read_git_context(repo_path).get("repo")


def fetch_pull_requests(
    repo_path: str,
    limit: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    """Return all closed PRs, optionally filtered to an event-time window."""
    slug = _repo_slug(repo_path)
    if not slug:
        raise DeriveError("could not determine the GitHub repository from its origin")
    raw = _run_gh(
        repo_path,
        "api", "--paginate", "--slurp",
        f"repos/{slug}/pulls?state=closed&per_page=100",
    )
    try:
        pages = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise DeriveError(f"could not parse gh output: {exc}")
    if not isinstance(pages, list):
        raise DeriveError("unexpected gh output shape")
    if pages and all(isinstance(page, list) for page in pages):
        data = [item for page in pages for item in page]
    else:
        data = pages

    normalised: list[dict] = []
    for pr in data:
        if not isinstance(pr, dict):
            continue
        merged_at = pr.get("mergedAt") or pr.get("merged_at")
        closed_at = pr.get("closedAt") or pr.get("closed_at")
        event_time = _parse_ts(merged_at) or _parse_ts(closed_at)
        if since and (event_time is None or event_time < since):
            continue
        if until and (event_time is None or event_time >= until):
            continue
        normalised.append({
            "number": pr.get("number"),
            "title": pr.get("title") or "",
            "mergedAt": merged_at,
            "closedAt": closed_at,
            "url": pr.get("url") or pr.get("html_url") or "",
            "author": pr.get("author") or {
                "login": (pr.get("user") or {}).get("login", "")
            },
        })
    return normalised if limit is None else normalised[:max(0, limit)]


def _repo_slug(repo_path: str) -> str | None:
    """owner/name from the remote, used only to build a stable outcome id."""
    try:
        raw = _run_gh(repo_path, "repo", "view", "--json", "nameWithOwner")
        return json.loads(raw).get("nameWithOwner")
    except (json.JSONDecodeError, AttributeError):
        return None


def build_outcomes(
    pull_requests: list[dict],
    workflow_id: str,
    slug: str | None,
) -> tuple[list, int]:
    """Turn PR records into Outcomes. Returns (outcomes, skipped_open_count).

    A merged PR is an accepted outcome; closed-without-merge is rejected. A PR
    that is somehow neither is skipped rather than guessed at — a wrong status
    silently moves money between the accepted and rework buckets.
    """
    from burnlens.storage.models import Outcome

    prefix = slug or "local"
    outcomes = []
    skipped = 0

    for pr in pull_requests:
        number = pr.get("number")
        if number is None:
            skipped += 1
            continue

        merged_at = _parse_ts(pr.get("mergedAt"))
        closed_at = _parse_ts(pr.get("closedAt"))

        if merged_at is not None:
            status, event_time = "accepted", merged_at
        elif closed_at is not None:
            status, event_time = "rejected", closed_at
        else:
            # Still open, or no timestamp to place it in time.
            skipped += 1
            continue

        outcomes.append(Outcome(
            # Stable across re-runs and unique across repos, so re-deriving is
            # a no-op rather than a double count.
            outcome_id=f"github:{prefix}#{number}",
            workflow_id=workflow_id,
            status=status,
            outcome_type="pull_request",
            event_time=event_time,
            source="derived",
            metadata={
                "pr_number": number,
                "title": pr.get("title") or "",
                "url": pr.get("url") or "",
                "author": (pr.get("author") or {}).get("login") or "",
            },
        ))

    return outcomes, skipped


async def derive_pr_outcomes(
    db_path: str,
    repo_path: str = ".",
    limit: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> DeriveResult:
    """Derive merged/closed PRs into the outcomes table. Idempotent.

    Re-running only ever adds newly-closed PRs: outcome ids are deterministic
    and the table dedups on them, so this is safe on a cron.
    """
    from burnlens.storage.database import init_db, reconcile_derived_outcome

    # gh first: the coding-agent loop's failure mode is "gh is missing", not
    # a later git or parse error that makes the user hunt for the real cause.
    if not gh_available():
        raise DeriveError(GH_MISSING_MESSAGE)

    resolved = str(Path(repo_path).expanduser().resolve())
    repo = _local_repo_name(resolved)
    if not repo:
        raise DeriveError(f"{resolved} is not inside a git repository")

    from burnlens.git_context import read_git_context

    stable_repo = read_git_context(resolved).get("repo_id") or repo
    workflow_id = repo_workflow_id(stable_repo)
    result = DeriveResult(
        repo=repo,
        workflow_id=workflow_id,
        scope_since=since.isoformat() if since else None,
        scope_until=until.isoformat() if until else None,
        import_complete=limit is None,
    )

    pull_requests = fetch_pull_requests(
        resolved, limit=limit, since=since, until=until
    )
    result.pull_requests_seen = len(pull_requests)

    outcomes, result.skipped_open = build_outcomes(
        pull_requests, workflow_id, _repo_slug(resolved)
    )

    await init_db(db_path)
    for outcome in outcomes:
        if outcome.status == "accepted":
            result.accepted += 1
        else:
            result.rejected += 1
        outcome_result = await reconcile_derived_outcome(db_path, outcome)
        if outcome_result == "inserted":
            result.inserted += 1
        elif outcome_result == "corrected":
            result.corrected += 1
        else:
            result.duplicates += 1

    logger.info(
        "Derived %d outcomes for %s (%d new, %d corrected, %d already recorded)",
        len(outcomes), workflow_id, result.inserted, result.corrected, result.duplicates,
    )
    return result
