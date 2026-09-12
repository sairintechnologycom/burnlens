"""Deterministic query tools for BurnLens Economics Analyst (BL-AE-002).

Enforces the critical architectural invariant:
LLMs NEVER calculate authoritative financial figures from raw data.
All metrics are derived deterministically by these tools with complete audit provenance.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from burnlens.storage.agent_economics import (
    get_agent_economics,
    get_task_economics,
    get_workflow_economics,
)

logger = logging.getLogger(__name__)


async def get_top_spending_agents(
    db_path: str, workspace_id: str, limit: int = 5, since: str | None = None
) -> dict[str, Any]:
    """Retrieve top spending agents in a workspace with exact spend figures."""
    conds = [
        "(workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))",
        "(agent_id IS NOT NULL OR json_extract(tags, '$.agent_id') IS NOT NULL)",
    ]
    params: list[Any] = [workspace_id, workspace_id]
    if since:
        conds.append("timestamp >= ?")
        params.append(since)

    where_clause = " WHERE " + " AND ".join(conds)

    query = f"""
        SELECT
            COALESCE(agent_id, json_extract(tags, '$.agent_id')) AS ag_id,
            COUNT(*) AS req_count,
            SUM(cost_usd) AS total_spend,
            SUM(input_tokens) AS in_tokens,
            SUM(output_tokens) AS out_tokens
        FROM requests
        {where_clause}
        GROUP BY ag_id
        ORDER BY total_spend DESC
        LIMIT ?
    """
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    agents = [
        {
            "agent_id": r[0],
            "requests_count": r[1],
            "total_spend_usd": round(r[2], 6),
            "input_tokens": r[3],
            "output_tokens": r[4],
        }
        for r in rows
    ]

    return {
        "workspace_id": workspace_id,
        "metric": "top_spending_agents",
        "provenance": "requests_table_deterministic_aggregate",
        "count": len(agents),
        "results": agents,
    }


async def get_workflow_waste_explanation(
    db_path: str, workflow_id: str, workspace_id: str
) -> dict[str, Any]:
    """Provide a deterministic breakdown of spend and waste for a specific workflow."""
    econ = await get_workflow_economics(db_path, workflow_id, workspace_id=workspace_id)

    # Detailed waste breakdown: status_code >= 400 errors, tool failures
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT status_code, COUNT(*), SUM(cost_usd)
            FROM requests
            WHERE (workflow_id = ? OR json_extract(tags, '$.workflow_id') = ?)
              AND (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
              AND status_code >= 400
            GROUP BY status_code
            """,
            (workflow_id, workflow_id, workspace_id, workspace_id),
        )
        error_rows = await cursor.fetchall()

    errors_breakdown = [
        {"status_code": r[0], "count": r[1], "waste_usd": round(r[2], 6)}
        for r in error_rows
    ]

    waste_ratio = (
        round(econ["retry_waste_usd"] / econ["total_spend_usd"], 4)
        if econ["total_spend_usd"] > 0
        else 0.0
    )

    return {
        "workspace_id": workspace_id,
        "workflow_id": workflow_id,
        "metric": "workflow_waste_explanation",
        "provenance": "workflow_economics_and_error_aggregation",
        "total_spend_usd": econ["total_spend_usd"],
        "model_spend_usd": econ["model_spend_usd"],
        "tool_action_spend_usd": econ["tool_action_spend_usd"],
        "retry_waste_usd": econ["retry_waste_usd"],
        "waste_ratio": waste_ratio,
        "accepted_outcomes": econ["accepted_outcomes"],
        "cost_per_accepted_outcome_usd": econ["cost_per_accepted_outcome_usd"],
        "error_details": errors_breakdown,
    }


async def get_agent_waste_ratio(
    db_path: str, agent_id: str, workspace_id: str
) -> dict[str, Any]:
    """Compute the exact proportion of spend attributed to retry waste for an agent."""
    econ = await get_agent_economics(db_path, agent_id, workspace_id=workspace_id)
    total_spend = econ["total_spend_usd"]
    retry_waste = econ["retry_waste_usd"]
    waste_percentage = (
        round((retry_waste / total_spend) * 100, 2) if total_spend > 0 else 0.0
    )

    return {
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "metric": "agent_retry_waste_ratio",
        "provenance": "agent_economics_aggregate",
        "total_spend_usd": total_spend,
        "retry_waste_usd": retry_waste,
        "retry_waste_percentage": waste_percentage,
        "requests_count": econ["requests_count"],
        "actions_count": econ["actions_count"],
    }


async def get_worst_cost_per_outcome_workflows(
    db_path: str, workspace_id: str, limit: int = 5
) -> dict[str, Any]:
    """Rank workflows by highest cost per accepted outcome."""
    async with aiosqlite.connect(db_path) as db:
        # Find distinct workflows
        cursor = await db.execute(
            """
            SELECT DISTINCT COALESCE(workflow_id, json_extract(tags, '$.workflow_id'))
            FROM requests
            WHERE (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
              AND (workflow_id IS NOT NULL OR json_extract(tags, '$.workflow_id') IS NOT NULL)
            """,
            (workspace_id, workspace_id),
        )
        wf_ids = [r[0] for r in await cursor.fetchall() if r[0]]

    results = []
    for wf_id in wf_ids:
        econ = await get_workflow_economics(db_path, wf_id, workspace_id=workspace_id)
        if econ["cost_per_accepted_outcome_usd"] is not None:
            results.append(econ)

    results.sort(key=lambda x: x["cost_per_accepted_outcome_usd"] or 0.0, reverse=True)
    trimmed = results[:limit]

    return {
        "workspace_id": workspace_id,
        "metric": "worst_cost_per_outcome_workflows",
        "provenance": "workflow_economics_outcome_join",
        "count": len(trimmed),
        "results": trimmed,
    }


async def investigate_task_costs(
    db_path: str, task_id: str, workspace_id: str
) -> dict[str, Any]:
    """Investigate the exact cost breakdown and actions of a single task."""
    econ = await get_task_economics(db_path, task_id, workspace_id=workspace_id)
    return {
        "workspace_id": workspace_id,
        "task_id": task_id,
        "metric": "task_cost_investigation",
        "provenance": "task_economics_and_actions",
        **econ,
    }
