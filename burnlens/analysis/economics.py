"""Runtime economics KPIs (BL-E2).

Composes figures that already exist rather than deriving anything new:

- total spend        → ``queries.get_total_cost``
- detected waste     → ``storage.findings.get_waste_summary`` (persisted findings)
- cost per accepted  → ``database.get_workflow_economics`` (the ONE allocation
  engine; do not re-derive cost-per-outcome here)
- error spend        → requests with a 4xx/5xx status

A note on what these numbers are NOT
------------------------------------
They do not partition spend. ``total = useful + waste + error`` is false and
must never be presented that way:

- Detectors overlap. One request can trip context bloat, history bloat and
  model overkill at once, and each estimates its own share of that request's
  cost as avoidable. Summing them can exceed the request's cost, so detected
  waste is an ESTIMATE OF AVOIDABLE SPEND, not a disjoint bucket.
- Error spend is a diagnostic dimension that overlaps waste, not a third
  bucket. A 200 response can still be wasted money, and a failed request inside
  a run that ultimately succeeded is not a failed run.

Hence: a rate, plus dimensions — never an additive breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class EconomicsOverview:
    """Top-line runtime economics for a window."""

    total_spend_usd: float
    detected_waste_usd: float
    waste_rate: float
    open_finding_count: int
    error_spend_usd: float
    error_request_count: int
    cost_per_accepted_usd: float | None
    accepted_count: int
    waste_by_detector: dict[str, float] = field(default_factory=dict)
    # True when detector estimates overlap enough to exceed total spend, so the
    # rate below has been clamped. Surfacing it beats quietly printing >100%.
    waste_estimate_clamped: bool = False


async def get_error_spend(db_path: str, since: str) -> tuple[float, int]:
    """Spend on requests the provider rejected (4xx/5xx).

    This is error spend, NOT failed-run cost. The proxy sees individual HTTP
    requests, so it cannot tell a failed run from a failed request inside a run
    that went on to succeed. Naming it failed-run cost would overstate it.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS spend, COUNT(*) AS count
              FROM requests
             WHERE timestamp >= ? AND status_code >= 400
            """,
            (since,),
        )
        row = await cursor.fetchone()
    return (float(row[0]), int(row[1]))


async def get_subject_spend(
    db_path: str,
    subject_type: str,
    subject_key: str,
    since: str,
    until: str | None = None,
) -> tuple[float, int]:
    """Spend and request count for one finding subject over a window.

    Subjects are the same two kinds the detectors produce: a tagged
    ``workflow_id``, or a model. Anything else has no rows and returns zeroes
    rather than silently matching everything.
    """
    if subject_type == "workflow":
        predicate = "json_extract(tags, '$.workflow_id') = ?"
    elif subject_type == "model":
        predicate = "model = ?"
    else:
        return (0.0, 0)

    query = (
        "SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM requests "
        f"WHERE {predicate} AND timestamp >= ?"
    )
    params: list[Any] = [subject_key, since]
    if until is not None:
        query += " AND timestamp < ?"
        params.append(until)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
    return (float(row[0]), int(row[1]))


async def get_economics_overview(
    db_path: str,
    since: str,
    window_seconds: int = 86_400,
) -> EconomicsOverview:
    """Assemble the top-line KPIs for a window."""
    from burnlens.storage.database import get_workflow_economics
    from burnlens.storage.findings import get_waste_summary
    from burnlens.storage.queries import get_total_cost

    total_spend = await get_total_cost(db_path, since=since)
    waste = await get_waste_summary(db_path)
    error_spend, error_count = await get_error_spend(db_path, since)

    # Reuse the existing allocation engine. Aggregate cost-per-accepted is
    # total attributed spend over accepted outcomes — failures charged to
    # successes, matching the per-workflow definition rather than inventing a
    # second one.
    workflows = await get_workflow_economics(
        db_path, since=since, window_seconds=window_seconds
    )
    accepted_count = sum(w.accepted_count for w in workflows)
    attributed_cost = sum(w.cost_total_usd for w in workflows)
    cost_per_accepted = (attributed_cost / accepted_count) if accepted_count else None

    detected_waste = waste["detected_waste_usd"]
    clamped = bool(total_spend) and detected_waste > total_spend
    if clamped:
        # Overlapping detectors can estimate more avoidable spend than was
        # actually spent. Report 100% rather than a nonsense figure, and say so.
        detected_waste = total_spend

    return EconomicsOverview(
        total_spend_usd=total_spend,
        detected_waste_usd=detected_waste,
        waste_rate=(detected_waste / total_spend) if total_spend else 0.0,
        open_finding_count=waste["open_finding_count"],
        error_spend_usd=error_spend,
        error_request_count=error_count,
        cost_per_accepted_usd=cost_per_accepted,
        accepted_count=accepted_count,
        waste_by_detector=waste["by_detector"],
        waste_estimate_clamped=clamped,
    )


def overview_to_dict(overview: EconomicsOverview) -> dict[str, Any]:
    """Serialise for the dashboard API."""
    return {
        "total_spend_usd": round(overview.total_spend_usd, 6),
        "detected_waste_usd": round(overview.detected_waste_usd, 6),
        "waste_rate": round(overview.waste_rate, 4),
        "open_finding_count": overview.open_finding_count,
        "error_spend_usd": round(overview.error_spend_usd, 6),
        "error_request_count": overview.error_request_count,
        "cost_per_accepted_usd": (
            round(overview.cost_per_accepted_usd, 6)
            if overview.cost_per_accepted_usd is not None
            else None
        ),
        "accepted_count": overview.accepted_count,
        "waste_by_detector": {
            k: round(v, 6) for k, v in overview.waste_by_detector.items()
        },
        "waste_estimate_clamped": overview.waste_estimate_clamped,
    }
