"""Economics-graph Phase C: outcomes derived from merged pull requests.

The point of this phase is that cost-per-outcome works with nothing to
integrate — a merged PR is already an accepted outcome, sitting in git.

The load-bearing thing under test is the join key. Agent session cost is tagged
by one code path (the scanners) and PR outcomes are written by another (the
deriver). If the two ever spell the workflow id differently there is no error
anywhere: the join simply matches nothing, every cost lands in "unattributed",
and the dashboard reads zero while looking perfectly healthy. Several tests here
exist only to make that impossible to do quietly.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from burnlens.outcomes import (
    DeriveError,
    _parse_ts,
    build_outcomes,
    derive_pr_outcomes,
)
from burnlens.scan._common import repo_workflow_id
from burnlens.storage.database import (
    get_workflow_economics,
    insert_outcome,
    insert_request,
)
from burnlens.storage.models import Outcome, RequestRecord

T0 = datetime.now(timezone.utc) - timedelta(hours=6)
SINCE = (T0 - timedelta(days=2)).isoformat()


def _pr(number, merged=True, minutes=0):
    ts = (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/acme/proj/pull/{number}",
        "author": {"login": "someone"},
        "mergedAt": ts if merged else None,
        "closedAt": ts,
    }


# ------------------------------------------------------------- the join key


def test_repo_workflow_id_is_namespaced():
    """Prefixed so a derived workflow can never collide with a workflow name a
    user picked for their own application traffic."""
    assert repo_workflow_id("burnlens") == "repo:burnlens"


def test_repo_workflow_id_without_repo_is_none():
    assert repo_workflow_id(None) is None
    assert repo_workflow_id("") is None


def test_scanners_tag_the_same_workflow_the_deriver_writes():
    """THE guard for this phase.

    Every scanner must route through repo_workflow_id rather than formatting the
    string itself. A hand-written 'repo:' anywhere is a silent join break, so
    assert the shared helper is imported and no scanner builds the prefix.
    """
    import inspect

    from burnlens.scan import claude_code, codex, cursor, gemini_cli

    for module in (claude_code, cursor, codex, gemini_cli):
        source = inspect.getsource(module)
        assert "repo_workflow_id" in source, (
            f"{module.__name__} does not use repo_workflow_id — its cost will "
            "never join to derived PR outcomes"
        )
        assert '"repo:' not in source and "'repo:" not in source, (
            f"{module.__name__} hand-writes the workflow prefix; it must call "
            "repo_workflow_id so the two sides cannot drift"
        )


def test_claude_scanner_emits_joinable_workflow_tag(tmp_path):
    """Behavioural counterpart to the source check above: parse a real session
    file and assert the tag it produces is the key the deriver writes."""
    from burnlens.scan.claude_code import ClaudeSession, parse_session

    session_file = tmp_path / "s1.jsonl"
    session_file.write_text(json.dumps({
        "type": "assistant",
        "timestamp": T0.isoformat().replace("+00:00", "Z"),
        "message": {
            "id": "msg_1",
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }) + "\n")

    session = ClaudeSession(
        session_id="s1",
        project_path=str(tmp_path),
        project_basename="burnlens",
        file_path=session_file,
        modified_at=T0,
    )
    with patch(
        "burnlens.scan.claude_code.resolve_dev_identity", return_value="dev@example.com"
    ):
        records = list(parse_session(session))

    assert records, "scanner produced no records"
    assert records[0].tags["workflow_id"] == repo_workflow_id("burnlens")


# ----------------------------------------------------------- classification


def test_merged_pr_is_accepted_and_closed_pr_is_rejected():
    outcomes, skipped = build_outcomes(
        [_pr(1, merged=True), _pr(2, merged=False)], "repo:proj", "acme/proj"
    )
    by_id = {o.outcome_id: o for o in outcomes}
    assert by_id["github:acme/proj#1"].status == "accepted"
    assert by_id["github:acme/proj#2"].status == "rejected"
    assert skipped == 0


def test_open_pr_is_skipped_not_guessed():
    """An open PR has no outcome yet. Guessing a status would move money
    between the accepted and rework buckets on no evidence."""
    still_open = {"number": 3, "mergedAt": None, "closedAt": None}
    outcomes, skipped = build_outcomes([still_open], "repo:proj", "acme/proj")
    assert outcomes == []
    assert skipped == 1


def test_outcome_ids_are_deterministic_and_repo_scoped():
    """Stable across runs so re-deriving dedups, and namespaced by repo so two
    repos' PR #1 are different outcomes."""
    first, _ = build_outcomes([_pr(1)], "repo:a", "acme/a")
    again, _ = build_outcomes([_pr(1)], "repo:a", "acme/a")
    other, _ = build_outcomes([_pr(1)], "repo:b", "acme/b")

    assert first[0].outcome_id == again[0].outcome_id
    assert first[0].outcome_id != other[0].outcome_id


def test_derived_outcomes_are_marked_as_derived():
    """`source` separates inferred outcomes from ones a customer reported, so
    the two can be told apart later."""
    outcomes, _ = build_outcomes([_pr(1)], "repo:proj", "acme/proj")
    assert outcomes[0].source == "derived"


def test_pr_metadata_is_retained():
    outcomes, _ = build_outcomes([_pr(7)], "repo:proj", "acme/proj")
    assert outcomes[0].metadata["pr_number"] == 7
    assert outcomes[0].metadata["author"] == "someone"


def test_malformed_pr_records_are_skipped_not_fatal():
    outcomes, skipped = build_outcomes(
        [{"title": "no number"}, _pr(1)], "repo:proj", "acme/proj"
    )
    assert len(outcomes) == 1
    assert skipped == 1


@pytest.mark.parametrize("raw,expected_year", [
    ("2026-08-09T12:00:00Z", 2026),
    ("2026-08-09T12:00:00+00:00", 2026),
])
def test_parse_ts_handles_rfc3339(raw, expected_year):
    assert _parse_ts(raw).year == expected_year


@pytest.mark.parametrize("raw", [None, "", "not-a-date"])
def test_parse_ts_returns_none_on_junk(raw):
    assert _parse_ts(raw) is None


# ------------------------------------------------------------- gh failures


async def test_missing_gh_gives_an_actionable_error(initialized_db, tmp_path):
    # A real repo, so the failure under test is the missing gh and not the
    # earlier not-a-git-repo check.
    with patch("burnlens.outcomes.shutil.which", return_value=None), \
         patch("burnlens.outcomes._local_repo_name", return_value="proj"):
        with pytest.raises(DeriveError, match="cli.github.com"):
            await derive_pr_outcomes(initialized_db, repo_path=str(tmp_path))


async def test_non_git_directory_is_reported(initialized_db, tmp_path):
    with patch("burnlens.outcomes._local_repo_name", return_value=None):
        with pytest.raises(DeriveError, match="not inside a git repository"):
            await derive_pr_outcomes(initialized_db, repo_path=str(tmp_path))


async def test_unauthenticated_gh_is_reported(initialized_db, tmp_path):
    import subprocess

    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="gh auth login required"
    )
    with patch("burnlens.outcomes.shutil.which", return_value="/usr/bin/gh"), \
         patch("burnlens.outcomes.subprocess.run", return_value=completed), \
         patch("burnlens.outcomes._local_repo_name", return_value="proj"):
        with pytest.raises(DeriveError, match="gh auth login"):
            await derive_pr_outcomes(initialized_db, repo_path=str(tmp_path))


# ----------------------------------------------------------------- end to end


async def _derive_with_fake_gh(db, tmp_path, prs, repo="proj"):
    """Run the real derive path with gh's output stubbed."""
    import subprocess

    def fake_run(args, **kwargs):
        if "pr" in args and "list" in args:
            out = json.dumps(prs)
        else:  # repo view
            out = json.dumps({"nameWithOwner": f"acme/{repo}"})
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=out, stderr="")

    with patch("burnlens.outcomes.shutil.which", return_value="/usr/bin/gh"), \
         patch("burnlens.outcomes.subprocess.run", side_effect=fake_run), \
         patch("burnlens.outcomes._local_repo_name", return_value=repo):
        return await derive_pr_outcomes(db, repo_path=str(tmp_path))


async def test_derive_is_idempotent(initialized_db, tmp_path):
    """Re-running must add nothing — otherwise a cron would inflate the merged-PR
    count and halve the reported cost per PR every night."""
    prs = [_pr(1), _pr(2), _pr(3, merged=False)]

    first = await _derive_with_fake_gh(initialized_db, tmp_path, prs)
    assert first.inserted == 3
    assert first.accepted == 2 and first.rejected == 1

    second = await _derive_with_fake_gh(initialized_db, tmp_path, prs)
    assert second.inserted == 0
    assert second.duplicates == 3

    rows = await get_workflow_economics(initialized_db, since=SINCE)
    assert rows[0].accepted_count == 2, "re-derive double-counted"


async def test_cost_per_merged_pr_end_to_end(initialized_db, tmp_path):
    """The Phase C promise: scan-shaped spend plus derived PR outcomes yields a
    cost per merged PR with nothing instrumented by hand."""
    workflow = repo_workflow_id("proj")

    # Two agent sessions' worth of cost, tagged the way the scanners tag it.
    for minutes, cost in ((0, 6.00), (5, 4.00)):
        await insert_request(initialized_db, RequestRecord(
            provider="anthropic", model="claude-sonnet-5", request_path="/v1/messages",
            timestamp=T0 + timedelta(minutes=minutes), cost_usd=cost,
            tags={"repo": "proj", "dev": "d@example.com", "workflow_id": workflow},
            source="scan_claude", request_id=f"req-{minutes}",
        ))

    await _derive_with_fake_gh(initialized_db, tmp_path, [_pr(1, minutes=10)])

    rows = await get_workflow_economics(initialized_db, since=SINCE)
    assert len(rows) == 1
    row = rows[0]
    assert row.workflow_id == workflow
    assert row.accepted_count == 1
    # $10 of agent spend produced one merged PR.
    assert row.cost_per_accepted_usd == pytest.approx(10.00)


async def test_spend_after_the_last_merge_is_unattributed(initialized_db, tmp_path):
    """Work in flight has produced no outcome yet; it must show as unattributed
    rather than inflating the cost of the last PR that happened to merge."""
    workflow = repo_workflow_id("proj")
    await insert_request(initialized_db, RequestRecord(
        provider="anthropic", model="claude-sonnet-5", request_path="/v1/messages",
        timestamp=T0, cost_usd=3.00,
        tags={"workflow_id": workflow}, source="scan_claude", request_id="a",
    ))
    await _derive_with_fake_gh(initialized_db, tmp_path, [_pr(1, minutes=5)])
    # Spend after the merge — still in progress.
    await insert_request(initialized_db, RequestRecord(
        provider="anthropic", model="claude-sonnet-5", request_path="/v1/messages",
        timestamp=T0 + timedelta(minutes=30), cost_usd=2.00,
        tags={"workflow_id": workflow}, source="scan_claude", request_id="b",
    ))

    row = (await get_workflow_economics(initialized_db, since=SINCE))[0]
    assert row.cost_accepted_usd == pytest.approx(3.00)
    assert row.cost_unattributed_usd == pytest.approx(2.00)
    assert row.cost_per_accepted_usd == pytest.approx(5.00)


async def test_derived_and_reported_outcomes_coexist(initialized_db, tmp_path):
    """A customer's own outcomes and BurnLens-derived ones live in one table and
    must not collide — the id namespaces keep them apart."""
    await insert_outcome(initialized_db, Outcome(
        outcome_id="ticket-1", workflow_id=repo_workflow_id("proj"),
        status="accepted", event_time=T0 + timedelta(minutes=1), source="api",
    ))
    result = await _derive_with_fake_gh(initialized_db, tmp_path, [_pr(1, minutes=2)])

    assert result.inserted == 1
    row = (await get_workflow_economics(initialized_db, since=SINCE))[0]
    assert row.accepted_count == 2
