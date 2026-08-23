#!/usr/bin/env python3
"""Flatten the local BurnLens DB into the cost-per-outcome snapshot the frontend imports.

Same shape as build_pricing_snapshot.py: the Next app deploys from `frontend/` as
its own Vercel root and cannot reach a SQLite file on a laptop at build time, so
generate, commit, and let a test fail when the JSON stops being self-consistent.

Unlike the pricing snapshot, CI cannot re-derive this from a checked-in source --
the source is one machine's dogfood database. That makes two things load-bearing:

* ``PUBLISHABLE`` is an explicit allowlist. Every other workflow in the database
  belongs to a private repo, and this script publishes repo names alongside spend.
  Never widen it to "every workflow with outcomes".
* The reported window is the INTERSECTION of the spend range and the outcome
  range, never the union. Outcomes here are derived from merged pull requests
  (see burnlens/outcomes.py), and git remembers PRs from long before the proxy
  recorded its first request. Dividing total spend by every PR ever merged
  charges 5 weeks of agent cost to 24 PRs that predate any telemetry, which
  understates the unit cost by a third.

Regenerate:  python scripts/build_outcome_snapshot.py
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "src" / "data" / "cost-per-outcome.json"
DB = Path(os.environ.get("BURNLENS_DB", Path.home() / ".burnlens" / "burnlens.db"))

# Public page, real repo names. Additions are a disclosure decision, not a code
# change -- the operator widened this to every repository on 2026-08-23.
#
# Every entry maps to a real git checkout on the build machine. Four workflow ids
# in the database do NOT and are deliberately absent: repo:sessions,
# repo:bhushan, repo:copilot and two "...chatgpt-conversation..." ids are
# artifacts of how agent session logs encode a working directory, not
# repositories anyone could look up. Publishing a name nothing can verify is
# worse than disclosing the spend as unattributed, which is what happens instead.
PUBLISHABLE = (
    "repo:deploymentlab",
    "repo:manan",
    "repo:zeroslateUI",
    "repo:burnlens",
    "repo:pkgsafe",
    "repo:strata",
    "repo:mediaOS",
    "repo:sutra",
    "repo:DermaLens",
    "repo:ShubhLifafa",
    "repo:SiteHQ",
    "repo:Infracanvas",
    "repo:interview_copilot",
)

_WINDOW = """
SELECT
    (SELECT MIN(timestamp) FROM requests
      WHERE json_extract(tags, '$.workflow_id') = :w),
    (SELECT MAX(timestamp) FROM requests
      WHERE json_extract(tags, '$.workflow_id') = :w)
"""

_SPEND = """
SELECT COUNT(*)                    AS requests,
       COALESCE(SUM(cost_usd), 0)  AS cost_usd,
       COALESCE(SUM(input_tokens), 0)        AS input_tokens,
       COALESCE(SUM(output_tokens), 0)       AS output_tokens,
       COALESCE(SUM(cache_read_tokens), 0)   AS cache_read_tokens,
       COALESCE(SUM(cache_write_tokens), 0)  AS cache_write_tokens
FROM requests
WHERE json_extract(tags, '$.workflow_id') = :w
"""

# Bounded by the spend window on both ends: an outcome outside it has no
# telemetry backing it, so it cannot honestly claim a share of the spend.
_OUTCOMES = """
SELECT status, COUNT(*)
FROM outcomes
WHERE workflow_id = :w AND event_time >= :start AND event_time <= :end
GROUP BY status
"""

_MODELS = """
SELECT model,
       COUNT(*)                   AS requests,
       COALESCE(SUM(cost_usd), 0) AS cost_usd
FROM requests
WHERE json_extract(tags, '$.workflow_id') = :w
GROUP BY model
ORDER BY cost_usd DESC
"""


def build_workflow(conn: sqlite3.Connection, workflow_id: str) -> dict | None:
    start, end = conn.execute(_WINDOW, {"w": workflow_id}).fetchone()
    if start is None:
        return None

    spend = dict(zip(
        ("requests", "cost_usd", "input_tokens", "output_tokens",
         "cache_read_tokens", "cache_write_tokens"),
        conn.execute(_SPEND, {"w": workflow_id}).fetchone(),
    ))
    counts = dict(conn.execute(
        _OUTCOMES, {"w": workflow_id, "start": start, "end": end}
    ).fetchall())
    accepted = counts.get("accepted", 0)
    # Merged PRs the window excluded. Without this a repo with 31 merged PRs
    # that all predate its telemetry looks identical to one that merged nothing,
    # and the first is the interesting case -- it is the window rule made visible.
    (accepted_all,) = conn.execute(
        "SELECT COUNT(*) FROM outcomes WHERE workflow_id = :w AND status = 'accepted'",
        {"w": workflow_id},
    ).fetchone()

    total_tokens = (
        spend["input_tokens"] + spend["output_tokens"]
        + spend["cache_read_tokens"] + spend["cache_write_tokens"]
    )
    prompt_tokens = spend["input_tokens"] + spend["cache_read_tokens"]

    return {
        "workflow_id": workflow_id,
        "window_start": start,
        "window_end": end,
        "requests": spend["requests"],
        "cost_usd": round(spend["cost_usd"], 4),
        "accepted": accepted,
        "accepted_outside_window": accepted_all - accepted,
        "rejected": counts.get("rejected", 0),
        "failed": counts.get("failed", 0),
        # Total spend over accepted outcomes, matching WorkflowEconomics: the
        # attempts that failed cost real money, and charging them to the ones
        # that landed is what a merged PR actually costs.
        "cost_per_accepted_usd": round(spend["cost_usd"] / accepted, 4) if accepted else None,
        "tokens_per_accepted": round(total_tokens / accepted) if accepted else None,
        "input_tokens": spend["input_tokens"],
        "output_tokens": spend["output_tokens"],
        "cache_read_tokens": spend["cache_read_tokens"],
        "cache_write_tokens": spend["cache_write_tokens"],
        # The number that makes input-only cost estimates wrong by an order of
        # magnitude on agent traffic.
        "cache_read_share": round(spend["cache_read_tokens"] / prompt_tokens, 4) if prompt_tokens else None,
        "models": [
            {"model": m, "requests": n, "cost_usd": round(c, 4)}
            for m, n, c in conn.execute(_MODELS, {"w": workflow_id})
        ],
    }


def build() -> dict:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        workflows = [w for wid in PUBLISHABLE if (w := build_workflow(conn, wid))]
        # Honest denominator: most rows in this database carry no workflow_id at
        # all, and a page that quotes unit economics without saying how much
        # spend never got attributed is quoting a number nobody can check.
        total, attributed = conn.execute("""
            SELECT COALESCE(SUM(cost_usd), 0),
                   COALESCE(SUM(CASE WHEN json_extract(tags, '$.workflow_id') IS NOT NULL
                                     THEN cost_usd END), 0)
            FROM requests
        """).fetchone()
    finally:
        conn.close()

    # Aggregate over published workflows only. Computed here rather than in the
    # page so the totals and the rows can never disagree about which repos are
    # in scope.
    pub_cost = sum(w["cost_usd"] for w in workflows)
    pub_accepted = sum(w["accepted"] for w in workflows)
    priced = [w for w in workflows if w["cost_per_accepted_usd"] is not None]

    return {
        "source": "burnlens dogfood database (local proxy + agent log scans)",
        "workflows": workflows,
        "published": {
            "repos": len(workflows),
            "repos_with_unit_cost": len(priced),
            "requests": sum(w["requests"] for w in workflows),
            "cost_usd": round(pub_cost, 4),
            "accepted": pub_accepted,
            # Blended, not an average of the per-repo rates: a mean of ratios
            # would weight a 2-PR repo the same as a 104-PR one.
            "cost_per_accepted_usd": round(pub_cost / pub_accepted, 4) if pub_accepted else None,
            "cheapest_usd": min((w["cost_per_accepted_usd"] for w in priced), default=None),
            "dearest_usd": max((w["cost_per_accepted_usd"] for w in priced), default=None),
        },
        "database": {
            "total_cost_usd": round(total, 4),
            "attributed_cost_usd": round(attributed, 4),
            "unattributed_cost_usd": round(total - attributed, 4),
        },
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
