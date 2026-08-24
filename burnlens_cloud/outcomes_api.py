"""Economics-graph Phase B: business outcomes and cost per accepted outcome.

Cost events answer "what did we spend". Outcomes answer "what did we get for
it". Joining them on `workflow_id` turns a cost dashboard into unit economics:

    cost_event -> workflow -> accepted_outcome

Two endpoints:

* ``POST /v1/outcomes`` — the caller's app reports business events. API-key
  auth, same as ``/v1/ingest``, because it is machine-to-machine from the same
  place the proxy runs.
* ``GET /api/v1/outcomes/summary`` — reads unit economics. JWT auth like every
  other dashboard route, or an API key, so the machine that posts outcomes can
  read back the economics it produced without a browser session.

**Allocation.** A request is charged to the first outcome of its workflow that
lands at-or-after it, within a window (default 24h). So the spend between two
consecutive outcomes belongs to the later one, and spend with no following
outcome inside the window is reported as unattributed rather than silently
dropped or spread around. The window is a query parameter, not stored config —
the right value is workload-specific and nobody knows it before seeing data.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from .auth import get_workspace_by_api_key, require_role, verify_token
from .database import execute_query
from .models import (
    OutcomeCoverage,
    OutcomeCoverageRow,
    OutcomeIngestRequest,
    OutcomeIngestResponse,
    ProviderConcentration,
    WorkflowEconomics,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["outcomes"])

# Default allocation window. 24h is long enough to cover a human-in-the-loop
# review cycle and short enough that yesterday's spend is not charged to today's
# outcome.
DEFAULT_WINDOW_SECONDS = 86_400


async def resolve_workspace(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """Workspace id from either a dashboard JWT or an API key.

    An API key is accepted on these reads because the caller that posts
    outcomes is usually the one that wants the economics back, and it has no
    browser session to carry a JWT. The key resolves to exactly one workspace
    and these routes return only that workspace's aggregates.

    JWT stays the first-class path: with no key present, the normal
    ``verify_token`` + role check applies unchanged.
    """
    if x_api_key:
        result = await get_workspace_by_api_key(x_api_key)
        if not result:
            logger.warning("Outcomes read with invalid API key")
            raise HTTPException(status_code=401, detail="Invalid API key")
        return str(result[0])

    token = await verify_token(request)
    await require_role("viewer", token)
    return str(token.workspace_id)


@router.post("/v1/outcomes", response_model=OutcomeIngestResponse)
async def ingest_outcomes(
    request: OutcomeIngestRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Record business outcomes. Idempotent on (workspace, outcome_id).

    Re-posting an outcome_id already on file is counted in `duplicates` and
    changes nothing — including its status. That is deliberate: a replayed
    delivery must not be able to overwrite a newer status with a stale one. To
    correct an outcome, post a new outcome_id.
    """
    api_key = request.api_key or x_api_key
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    workspace_result = await get_workspace_by_api_key(api_key)
    if not workspace_result:
        logger.warning("Outcome ingest with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    workspace_id, _plan = workspace_result

    if not request.outcomes:
        return OutcomeIngestResponse(accepted=0, duplicates=0)

    # Within-batch duplicates would make the rowcount ambiguous, so collapse
    # them here — first occurrence wins, matching the DB's ON CONFLICT.
    seen: set[str] = set()
    rows = []
    for o in request.outcomes:
        if o.outcome_id in seen:
            continue
        seen.add(o.outcome_id)
        rows.append(o)

    inserted = 0
    for o in rows:
        # RETURNING id yields no row when ON CONFLICT DO NOTHING suppressed the
        # insert, which is how a duplicate is detected without a second query.
        result = await execute_query(
            """
            INSERT INTO outcomes
                (workspace_id, outcome_id, workflow_id, status, business_value,
                 currency, event_time, source, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
            ON CONFLICT (workspace_id, outcome_id) DO NOTHING
            RETURNING id
            """,
            workspace_id,
            o.outcome_id,
            o.workflow_id,
            o.status,
            o.business_value,
            o.currency,
            o.event_time,
            o.source,
            json.dumps(o.metadata),
        )
        if result:
            inserted += 1

    logger.info(
        "outcomes.ingested workspace=%s accepted=%d duplicates=%d",
        workspace_id,
        inserted,
        len(request.outcomes) - inserted,
    )
    return OutcomeIngestResponse(
        accepted=inserted,
        duplicates=len(request.outcomes) - inserted,
    )


# The allocation join. Each request finds the first outcome of its workflow at
# or after it, inside the window; requests that find none land in the
# unattributed bucket. FULL OUTER JOIN so a workflow that only spent money and a
# workflow that only produced outcomes both still appear — either one alone is a
# signal worth seeing.
_SUMMARY_SQL = """
WITH req AS (
    SELECT r.ts, r.cost_usd, r.tags->>'workflow_id' AS workflow_id
    FROM request_records r
    WHERE r.workspace_id = $1
      AND r.ts >= $2
      AND r.tags->>'workflow_id' IS NOT NULL
),
alloc AS (
    SELECT
        req.workflow_id,
        req.cost_usd,
        (
            SELECT o.status
            FROM outcomes o
            WHERE o.workspace_id = $1
              AND o.workflow_id = req.workflow_id
              AND o.event_time >= req.ts
              AND o.event_time < req.ts + ($3 * interval '1 second')
            ORDER BY o.event_time ASC
            LIMIT 1
        ) AS status
    FROM req
),
spend AS (
    SELECT
        workflow_id,
        COALESCE(SUM(cost_usd), 0) AS cost_total,
        COALESCE(SUM(cost_usd) FILTER (WHERE status = 'accepted'), 0) AS cost_accepted,
        COALESCE(SUM(cost_usd) FILTER (WHERE status IN ('rejected', 'failed')), 0) AS cost_rework,
        COALESCE(SUM(cost_usd) FILTER (WHERE status IS NULL), 0) AS cost_unattributed
    FROM alloc
    GROUP BY workflow_id
),
counts AS (
    SELECT
        workflow_id,
        COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_count,
        COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count,
        COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
        SUM(business_value) FILTER (WHERE status = 'accepted') AS business_value_accepted
    FROM outcomes
    WHERE workspace_id = $1 AND event_time >= $2
    GROUP BY workflow_id
)
SELECT
    workflow_id,
    COALESCE(s.cost_total, 0) AS cost_total,
    COALESCE(s.cost_accepted, 0) AS cost_accepted,
    COALESCE(s.cost_rework, 0) AS cost_rework,
    COALESCE(s.cost_unattributed, 0) AS cost_unattributed,
    COALESCE(c.accepted_count, 0) AS accepted_count,
    COALESCE(c.rejected_count, 0) AS rejected_count,
    COALESCE(c.failed_count, 0) AS failed_count,
    c.business_value_accepted
FROM spend s
FULL OUTER JOIN counts c USING (workflow_id)
ORDER BY cost_total DESC
"""


@router.get("/api/v1/outcomes/summary", response_model=list[WorkflowEconomics])
async def outcomes_summary(
    workspace_id: str = Depends(resolve_workspace),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    window_seconds: int = Query(
        DEFAULT_WINDOW_SECONDS,
        ge=1,
        le=604_800,
        description="How long after a request an outcome may still claim its cost",
    ),
):
    """Per-workflow unit economics: what an accepted outcome actually costs."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await execute_query(_SUMMARY_SQL, workspace_id, cutoff, float(window_seconds))

    out: list[WorkflowEconomics] = []
    for r in rows:
        accepted = int(r["accepted_count"])
        cost_total = float(r["cost_total"])
        out.append(
            WorkflowEconomics(
                workflow_id=r["workflow_id"],
                accepted_count=accepted,
                rejected_count=int(r["rejected_count"]),
                failed_count=int(r["failed_count"]),
                cost_total_usd=cost_total,
                cost_accepted_usd=float(r["cost_accepted"]),
                cost_rework_usd=float(r["cost_rework"]),
                cost_unattributed_usd=float(r["cost_unattributed"]),
                # Guarded rather than computed in SQL: a workflow with spend but
                # no accepted outcomes is the interesting case, not an error.
                cost_per_accepted_usd=(cost_total / accepted) if accepted else None,
                business_value_accepted=(
                    float(r["business_value_accepted"])
                    if r["business_value_accepted"] is not None
                    else None
                ),
            )
        )
    return out


# Same allocation rule as _SUMMARY_SQL, narrowed to accepted outcomes: spend
# share says who is expensive, and only the outcome join says who the workspace
# cannot leave.
#
# `wf_providers` is what makes this more than a group-by. A provider carrying 20%
# of spend but the ONLY provider on the workflows it touches is a harder
# dependency than one carrying 60% across workflows two other providers also
# serve, and no spend-ranked table can show that.
_CONCENTRATION_SQL = """
WITH req AS (
    SELECT r.ts, r.provider, r.cost_usd, r.tags->>'workflow_id' AS workflow_id
    FROM request_records r
    WHERE r.workspace_id = $1
      AND r.ts >= $2
      AND r.tags->>'workflow_id' IS NOT NULL
),
alloc AS (
    SELECT
        req.provider,
        req.cost_usd,
        req.workflow_id,
        (
            SELECT o.outcome_id
            FROM outcomes o
            WHERE o.workspace_id = $1
              AND o.workflow_id = req.workflow_id
              AND o.status = 'accepted'
              AND o.event_time >= req.ts
              AND o.event_time < req.ts + ($3 * interval '1 second')
            ORDER BY o.event_time ASC
            LIMIT 1
        ) AS accepted_outcome_id
    FROM req
),
wf_providers AS (
    SELECT workflow_id, COUNT(DISTINCT provider) AS n_providers
    FROM req
    GROUP BY workflow_id
),
totals AS (
    -- DISTINCT, not a sum of the per-provider counts: an outcome several
    -- providers contributed to would otherwise inflate the denominator and
    -- shrink every share.
    SELECT
        COALESCE(SUM(cost_usd), 0) AS spend,
        COUNT(DISTINCT accepted_outcome_id) AS accepted
    FROM alloc
)
SELECT
    a.provider,
    COALESCE(SUM(a.cost_usd), 0) AS spend_usd,
    COUNT(DISTINCT a.accepted_outcome_id) AS accepted_outcomes,
    COUNT(DISTINCT a.workflow_id) AS workflows,
    COUNT(DISTINCT a.workflow_id) FILTER (WHERE w.n_providers = 1)
        AS sole_provider_workflows,
    t.spend AS total_spend,
    t.accepted AS total_accepted
FROM alloc a
JOIN wf_providers w USING (workflow_id)
CROSS JOIN totals t
GROUP BY a.provider, t.spend, t.accepted
ORDER BY spend_usd DESC
"""


@router.get("/api/v1/outcomes/concentration", response_model=list[ProviderConcentration])
async def outcomes_concentration(
    workspace_id: str = Depends(resolve_workspace),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    window_seconds: int = Query(
        DEFAULT_WINDOW_SECONDS,
        ge=1,
        le=604_800,
        description="How long after a request an outcome may still claim its cost",
    ),
):
    """Which providers the workspace's accepted outcomes actually depend on."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await execute_query(_CONCENTRATION_SQL, workspace_id, cutoff, float(window_seconds))

    out: list[ProviderConcentration] = []
    for r in rows:
        total_spend = float(r["total_spend"])
        total_accepted = int(r["total_accepted"])
        spend = float(r["spend_usd"])
        accepted = int(r["accepted_outcomes"])
        out.append(
            ProviderConcentration(
                provider=r["provider"],
                spend_usd=spend,
                # Guarded rather than divided in SQL: a window with outcomes but
                # no attributed spend is a real state, not a division error.
                spend_share=(spend / total_spend) if total_spend else 0.0,
                accepted_outcomes=accepted,
                accepted_share=(accepted / total_accepted) if total_accepted else 0.0,
                workflows=int(r["workflows"]),
                sole_provider_workflows=int(r["sole_provider_workflows"]),
            )
        )
    return out


# --------------------------------------------------------------- outcome coverage

# Same allocation rule as _SUMMARY_SQL, but deliberately NOT filtered to rows
# carrying a workflow_id. Untagged spend is the number this endpoint exists to
# report, and the summary query cannot see it by construction.
_COVERAGE_SQL = """
WITH alloc AS (
    SELECT
        r.tags->>'workflow_id' AS workflow_id,
        r.cost_usd,
        CASE WHEN r.tags->>'workflow_id' IS NULL THEN NULL ELSE (
            SELECT o.status
            FROM outcomes o
            WHERE o.workspace_id = $1
              AND o.workflow_id = r.tags->>'workflow_id'
              AND o.event_time >= r.ts
              AND o.event_time < r.ts + ($3 * interval '1 second')
            ORDER BY o.event_time ASC
            LIMIT 1
        ) END AS status
    FROM request_records r
    WHERE r.workspace_id = $1 AND r.ts >= $2
)
SELECT
    workflow_id,
    COALESCE(SUM(cost_usd), 0) AS cost_total,
    COALESCE(SUM(cost_usd) FILTER (WHERE status IS NOT NULL), 0) AS cost_attributed,
    COALESCE(SUM(cost_usd) FILTER (WHERE status = 'accepted'), 0) AS cost_accepted,
    COALESCE(SUM(cost_usd) FILTER (WHERE status IN ('rejected', 'failed')), 0) AS cost_rework
FROM alloc
GROUP BY workflow_id
ORDER BY cost_total DESC
"""


@router.get("/api/v1/outcomes/coverage", response_model=OutcomeCoverage)
async def outcomes_coverage(
    workspace_id: str = Depends(resolve_workspace),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    window_seconds: int = Query(
        DEFAULT_WINDOW_SECONDS,
        ge=1,
        le=604_800,
        description="How long after a request an outcome may still claim its cost",
    ),
    limit: int = Query(20, ge=1, le=200, description="Workflows in the breakdown"),
):
    """What share of spend reaches a recorded outcome — and what share never can."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await execute_query(_COVERAGE_SQL, workspace_id, cutoff, float(window_seconds))

    total = attributed = accepted = rework = untagged = 0.0
    by_workflow: list[OutcomeCoverageRow] = []
    for r in rows:
        cost_total = float(r["cost_total"])
        cost_attributed = float(r["cost_attributed"])
        total += cost_total
        attributed += cost_attributed
        accepted += float(r["cost_accepted"])
        rework += float(r["cost_rework"])
        if r["workflow_id"] is None:
            untagged += cost_total
        by_workflow.append(
            OutcomeCoverageRow(
                workflow_id=r["workflow_id"],
                cost_total_usd=round(cost_total, 6),
                cost_attributed_usd=round(cost_attributed, 6),
                coverage_pct=round(cost_attributed / cost_total * 100, 1) if cost_total else 0.0,
            )
        )

    return OutcomeCoverage(
        days=days,
        window_seconds=window_seconds,
        cost_total_usd=round(total, 6),
        cost_attributed_usd=round(attributed, 6),
        # Tagged with a workflow but nothing came back for it, as distinct from
        # never tagged at all — one is a missing POST, the other a missing tag.
        cost_unattributed_usd=round(total - attributed - untagged, 6),
        cost_untagged_usd=round(untagged, 6),
        cost_accepted_usd=round(accepted, 6),
        cost_rework_usd=round(rework, 6),
        coverage_pct=round(attributed / total * 100, 1) if total else 0.0,
        by_workflow=by_workflow[:limit],
    )
