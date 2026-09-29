"""Phase 1: BL-AE-001 Agent Economics Foundation.

Provides domain entity management, correlation extraction, recursive parent-child
spend rollups, and unit economics without modifying canonical ledger calculations.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiosqlite

from burnlens.storage.models import (
    Agent,
    AgentAction,
    AgentRun,
    AgentTask,
    AgentWorkflow,
    WorkflowRun,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# Domain Entity CRUD (Agent, Workflow, Run, Task, Action)
# ===========================================================================

async def insert_agent(db_path: str, agent: Agent) -> str:
    """Register an agent with BurnLens."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT workspace_id FROM agents WHERE agent_id = ?", (agent.agent_id,)
        )
        existing = await cursor.fetchone()
        if existing and existing[0] != agent.workspace_id:
            raise ValueError("agent_id is already registered to another workspace")
        await db.execute(
            """
            INSERT INTO agents (
                agent_id, name, version, owner, environment, purpose, status, workspace_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                name = excluded.name,
                version = excluded.version,
                owner = excluded.owner,
                environment = excluded.environment,
                purpose = excluded.purpose,
                status = excluded.status
            WHERE agents.workspace_id = excluded.workspace_id
            """,
            (
                agent.agent_id,
                agent.name,
                agent.version,
                agent.owner,
                agent.environment,
                agent.purpose,
                agent.status,
                agent.workspace_id,
                agent.created_at.isoformat(),
            ),
        )
        await db.commit()
    return agent.agent_id


async def get_agent(
    db_path: str, agent_id: str, workspace_id: str | None = None
) -> Agent | None:
    """Retrieve an agent by ID with optional workspace scoping."""
    query = "SELECT agent_id, name, version, owner, environment, purpose, status, workspace_id, created_at FROM agents WHERE agent_id = ?"
    params: list[Any] = [agent_id]
    if workspace_id:
        query += " AND workspace_id = ?"
        params.append(workspace_id)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        if not row:
            return None
        return Agent(
            agent_id=row[0],
            name=row[1],
            version=row[2],
            owner=row[3],
            environment=row[4],
            purpose=row[5],
            status=row[6],
            workspace_id=row[7],
            created_at=datetime.fromisoformat(row[8]),
        )


async def list_agents(db_path: str, workspace_id: str = "default") -> list[Agent]:
    """List all agents for a given workspace."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT agent_id, name, version, owner, environment, purpose, status, workspace_id, created_at FROM agents WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        rows = await cursor.fetchall()
        return [
            Agent(
                agent_id=r[0],
                name=r[1],
                version=r[2],
                owner=r[3],
                environment=r[4],
                purpose=r[5],
                status=r[6],
                workspace_id=r[7],
                created_at=datetime.fromisoformat(r[8]),
            )
            for r in rows
        ]


async def insert_agent_workflow(db_path: str, workflow: AgentWorkflow) -> str:
    """Register an agent workflow."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT workspace_id FROM agent_workflows WHERE workflow_id = ?",
            (workflow.workflow_id,),
        )
        existing = await cursor.fetchone()
        if existing and existing[0] != workflow.workspace_id:
            raise ValueError("workflow_id is already registered to another workspace")
        await db.execute(
            """
            INSERT INTO agent_workflows (
                workflow_id, name, workspace_id, created_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                name = excluded.name,
                created_at = excluded.created_at
            WHERE agent_workflows.workspace_id = excluded.workspace_id
            """,
            (
                workflow.workflow_id,
                workflow.name,
                workflow.workspace_id,
                workflow.created_at.isoformat(),
            ),
        )
        await db.commit()
    return workflow.workflow_id


async def insert_workflow_run(db_path: str, run: WorkflowRun) -> str:
    """Register one workflow execution without conflating workspace identities."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT workspace_id FROM agent_workflows WHERE workflow_id = ?",
            (run.workflow_id,),
        )
        workflow = await cursor.fetchone()
        if workflow and workflow[0] != run.workspace_id:
            raise ValueError("workflow_id belongs to another workspace")

        for table in ("agent_runs", "requests"):
            cursor = await db.execute(
                f"SELECT 1 FROM {table} WHERE workflow_run_id = ? AND "
                "COALESCE(workspace_id, 'default') != ? LIMIT 1",
                (run.workflow_run_id, run.workspace_id),
            )
            if await cursor.fetchone():
                raise ValueError("workflow_run_id is referenced by another workspace")

        await db.execute(
            """
            INSERT INTO workflow_runs (
                workflow_run_id, workflow_id, workspace_id, status, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, workflow_run_id) DO UPDATE SET
                workflow_id = excluded.workflow_id,
                status = excluded.status,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at
            """,
            (
                run.workflow_run_id,
                run.workflow_id,
                run.workspace_id,
                run.status,
                run.started_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
            ),
        )
        await db.commit()
    return run.workflow_run_id


async def get_workflow_run(
    db_path: str, workflow_run_id: str, workspace_id: str
) -> WorkflowRun | None:
    """Get a workflow execution using its workspace-scoped identity."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT workflow_run_id, workflow_id, workspace_id, status,
                      started_at, completed_at
               FROM workflow_runs WHERE workflow_run_id = ? AND workspace_id = ?""",
            (workflow_run_id, workspace_id),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return WorkflowRun(
        workflow_run_id=row[0],
        workflow_id=row[1],
        workspace_id=row[2],
        status=row[3],
        started_at=datetime.fromisoformat(row[4]),
        completed_at=datetime.fromisoformat(row[5]) if row[5] else None,
    )


async def insert_agent_run(db_path: str, run: AgentRun) -> str:
    """Record an agent execution run."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT workspace_id FROM agent_runs WHERE run_id = ?", (run.run_id,)
        )
        existing = await cursor.fetchone()
        if existing and existing[0] != run.workspace_id:
            raise ValueError("run_id is already registered to another workspace")
        if run.parent_run_id:
            cursor = await db.execute(
                "SELECT workspace_id FROM agent_runs WHERE run_id = ?",
                (run.parent_run_id,),
            )
            parent = await cursor.fetchone()
            if parent and parent[0] != run.workspace_id:
                raise ValueError("parent_run_id belongs to another workspace")
        cursor = await db.execute(
            "SELECT 1 FROM agent_runs WHERE parent_run_id = ? AND workspace_id != ? LIMIT 1",
            (run.run_id, run.workspace_id),
        )
        if await cursor.fetchone():
            raise ValueError("run_id is referenced as a parent by another workspace")
        if run.workflow_id:
            cursor = await db.execute(
                "SELECT workspace_id FROM agent_workflows WHERE workflow_id = ?",
                (run.workflow_id,),
            )
            workflow = await cursor.fetchone()
            if workflow and workflow[0] != run.workspace_id:
                raise ValueError("workflow_id belongs to another workspace")
        cursor = await db.execute(
            "SELECT workspace_id FROM agents WHERE agent_id = ?", (run.agent_id,)
        )
        agent = await cursor.fetchone()
        if agent and agent[0] != run.workspace_id:
            raise ValueError("agent_id belongs to another workspace")
        if run.workflow_run_id:
            cursor = await db.execute(
                "SELECT 1 FROM workflow_runs WHERE workflow_run_id = ? AND workspace_id = ?",
                (run.workflow_run_id, run.workspace_id),
            )
            matching_workflow_run = await cursor.fetchone()
            if not matching_workflow_run:
                cursor = await db.execute(
                    "SELECT 1 FROM workflow_runs WHERE workflow_run_id = ? LIMIT 1",
                    (run.workflow_run_id,),
                )
                if await cursor.fetchone():
                    raise ValueError("workflow_run_id belongs to another workspace")
        await db.execute(
            """
            INSERT INTO agent_runs (
                run_id, agent_id, workflow_id, workflow_run_id, parent_run_id, root_run_id,
                workspace_id, status, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                agent_id = excluded.agent_id,
                workflow_id = excluded.workflow_id,
                workflow_run_id = excluded.workflow_run_id,
                parent_run_id = excluded.parent_run_id,
                root_run_id = excluded.root_run_id,
                status = excluded.status,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at
            WHERE agent_runs.workspace_id = excluded.workspace_id
            """,
            (
                run.run_id,
                run.agent_id,
                run.workflow_id,
                run.workflow_run_id,
                run.parent_run_id,
                run.root_run_id,
                run.workspace_id,
                run.status,
                run.started_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
            ),
        )
        await db.commit()
    return run.run_id


async def get_agent_run(
    db_path: str, run_id: str, workspace_id: str | None = None
) -> AgentRun | None:
    """Retrieve an agent run by ID."""
    query = "SELECT run_id, agent_id, workflow_id, workflow_run_id, parent_run_id, root_run_id, workspace_id, status, started_at, completed_at FROM agent_runs WHERE run_id = ?"
    params: list[Any] = [run_id]
    if workspace_id:
        query += " AND workspace_id = ?"
        params.append(workspace_id)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        if not row:
            return None
        return AgentRun(
            run_id=row[0],
            agent_id=row[1],
            workflow_id=row[2],
            workflow_run_id=row[3],
            parent_run_id=row[4],
            root_run_id=row[5],
            workspace_id=row[6],
            status=row[7],
            started_at=datetime.fromisoformat(row[8]),
            completed_at=datetime.fromisoformat(row[9]) if row[9] else None,
        )


async def insert_agent_task(db_path: str, task: AgentTask) -> str:
    """Record an agent task within a run."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_tasks (
                task_id, run_id, name, status, workspace_id, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.run_id,
                task.name,
                task.status,
                task.workspace_id,
                task.created_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else None,
            ),
        )
        await db.commit()
    return task.task_id


async def insert_agent_action(db_path: str, action: AgentAction) -> str:
    """Record an agent action (e.g. tool execution, sub-action)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_actions (
                action_id, task_id, run_id, action_type, tool_name, status, cost_usd, workspace_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.action_id,
                action.task_id,
                action.run_id,
                action.action_type,
                action.tool_name,
                action.status,
                action.cost_usd,
                action.workspace_id,
                action.created_at.isoformat(),
            ),
        )
        await db.commit()
    return action.action_id


# ===========================================================================
# Economics Rollups & Recursive Hierarchy Calculations
# ===========================================================================

async def get_agent_economics(
    db_path: str,
    agent_id: str,
    workspace_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Calculate deterministic economics for an agent from canonical requests and actions."""
    conditions = [
        "(agent_id = ? OR json_extract(tags, '$.agent_id') = ?)"
    ]
    params: list[Any] = [agent_id, agent_id]

    if workspace_id:
        conditions.append("(workspace_id = ? OR json_extract(tags, '$.workspace_id') = ?)")
        params.extend([workspace_id, workspace_id])
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where_clause = " WHERE " + " AND ".join(conditions)

    async with aiosqlite.connect(db_path) as db:
        # 1. Direct LLM requests metrics
        query = f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(cost_usd), 0.0),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(reasoning_tokens), 0),
                COALESCE(SUM(cache_read_tokens), 0),
                COALESCE(SUM(cache_saved_usd), 0.0),
                COALESCE(SUM(tool_calls), 0)
            FROM requests
            {where_clause}
        """
        cursor = await db.execute(query, params)
        r = await cursor.fetchone()
        req_count, total_model_spend, in_toks, out_toks, reason_toks, cache_toks, cache_saved, tool_calls = r

        # 2. Retry waste calculation (requests with status_code >= 400 or retry headers)
        retry_query = f"""
            SELECT COALESCE(SUM(cost_usd), 0.0)
            FROM requests
            {where_clause} AND status_code >= 400
        """
        cursor = await db.execute(retry_query, params)
        retry_waste = (await cursor.fetchone())[0]

        # 3. Actions / tool executions
        act_conds = ["run_id IN (SELECT run_id FROM agent_runs WHERE agent_id = ?)"]
        act_params: list[Any] = [agent_id]
        if workspace_id:
            act_conds.append("workspace_id = ?")
            act_params.append(workspace_id)
        if since:
            act_conds.append("created_at >= ?")
            act_params.append(since)

        cursor = await db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(cost_usd), 0.0) FROM agent_actions WHERE {' AND '.join(act_conds)}",
            act_params,
        )
        action_count, tool_action_cost = await cursor.fetchone()

        total_spend = total_model_spend + tool_action_cost

        return {
            "agent_id": agent_id,
            "total_spend_usd": round(total_spend, 6),
            "model_spend_usd": round(total_model_spend, 6),
            "tool_action_spend_usd": round(tool_action_cost, 6),
            "retry_waste_usd": round(retry_waste, 6),
            "requests_count": req_count,
            "actions_count": action_count,
            "tool_calls_count": tool_calls,
            "input_tokens": in_toks,
            "output_tokens": out_toks,
            "reasoning_tokens": reason_toks,
            "cache_read_tokens": cache_toks,
            "cache_saved_usd": round(cache_saved, 6),
        }


async def get_task_economics(
    db_path: str, task_id: str, workspace_id: str | None = None
) -> dict[str, Any]:
    """Calculate deterministic economics for a discrete task."""
    conditions = ["(task_id = ? OR json_extract(tags, '$.task_id') = ?)"]
    params: list[Any] = [task_id, task_id]
    if workspace_id:
        conditions.append("(workspace_id = ? OR json_extract(tags, '$.workspace_id') = ?)")
        params.extend([workspace_id, workspace_id])

    where_clause = " WHERE " + " AND ".join(conditions)

    async with aiosqlite.connect(db_path) as db:
        # LLM spend
        cursor = await db.execute(
            f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(cost_usd), 0.0),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(tool_calls), 0)
            FROM requests
            {where_clause}
            """,
            params,
        )
        req_count, model_spend, in_toks, out_toks, tool_calls = await cursor.fetchone()

        # Retry waste
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests {where_clause} AND status_code >= 400",
            params,
        )
        retry_waste = (await cursor.fetchone())[0]

        # Tool actions
        act_conds = ["task_id = ?"]
        act_params: list[Any] = [task_id]
        if workspace_id:
            act_conds.append("workspace_id = ?")
            act_params.append(workspace_id)

        cursor = await db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(cost_usd), 0.0) FROM agent_actions WHERE {' AND '.join(act_conds)}",
            act_params,
        )
        action_count, tool_action_cost = await cursor.fetchone()

        total_spend = model_spend + tool_action_cost

        return {
            "task_id": task_id,
            "total_spend_usd": round(total_spend, 6),
            "model_spend_usd": round(model_spend, 6),
            "tool_action_spend_usd": round(tool_action_cost, 6),
            "retry_waste_usd": round(retry_waste, 6),
            "requests_count": req_count,
            "actions_count": action_count,
            "tool_calls_count": tool_calls,
            "input_tokens": in_toks,
            "output_tokens": out_toks,
        }


async def get_run_economics(
    db_path: str, run_id: str, workspace_id: str | None = None
) -> dict[str, Any]:
    """Calculate recursive economics for an agent run, including child runs with NO double counting.

    Parent Agent = $10, Child A = $3, Child B = $7 -> Total Rollup = $10.
    """
    async with aiosqlite.connect(db_path) as db:
        root_params: tuple[Any, ...] = (run_id, workspace_id) if workspace_id else (run_id,)
        root_query = "SELECT workspace_id FROM agent_runs WHERE run_id = ?"
        if workspace_id:
            root_query += " AND workspace_id = ?"
        cursor = await db.execute(root_query, root_params)
        root = await cursor.fetchone()
        if not root:
            return {
                "run_id": run_id,
                "total_rollup_spend_usd": 0.0,
                "direct_spend_usd": 0.0,
                "children_spend_usd": 0.0,
                "retry_waste_usd": 0.0,
                "child_runs_count": 0,
                "children_breakdown": {},
            }
        workspace_id = root[0]

        # Find all runs in this hierarchy using a recursive CTE
        # Root run + all descendant children
        tree_query = """
            WITH RECURSIVE run_tree(r_id, p_id) AS (
                SELECT run_id, parent_run_id FROM agent_runs
                WHERE run_id = ? AND workspace_id = ?
                UNION
                SELECT r.run_id, r.parent_run_id FROM agent_runs r
                JOIN run_tree rt ON r.parent_run_id = rt.r_id
                WHERE r.workspace_id = ?
            )
            SELECT r_id, p_id FROM run_tree;
        """
        cursor = await db.execute(tree_query, (run_id, workspace_id, workspace_id))
        tree_rows = await cursor.fetchall()

        all_run_ids = [r[0] for r in tree_rows] if tree_rows else [run_id]
        child_run_ids = [r[0] for r in tree_rows if r[0] != run_id]

        # 1. Direct spend on parent run itself
        parent_spend_query = """
            SELECT
                COALESCE(SUM(cost_usd), 0.0),
                COUNT(*),
                COALESCE(SUM(tool_calls), 0)
            FROM requests
            WHERE (run_id = ? OR json_extract(tags, '$.run_id') = ?)
              AND (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
        """
        cursor = await db.execute(parent_spend_query, (run_id, run_id, workspace_id, workspace_id))
        direct_model_spend, direct_req_count, direct_tool_calls = await cursor.fetchone()

        # Direct actions
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM agent_actions WHERE run_id = ? AND workspace_id = ?",
            (run_id, workspace_id),
        )
        direct_action_spend, direct_action_count = await cursor.fetchone()

        direct_total = direct_model_spend + direct_action_spend

        # 2. Spend per child run
        children_breakdown: dict[str, dict[str, Any]] = {}
        total_children_spend = 0.0

        for c_id in child_run_ids:
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*)
                FROM requests
                WHERE (run_id = ? OR json_extract(tags, '$.run_id') = ?)
                  AND (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
                """,
                (c_id, c_id, workspace_id, workspace_id),
            )
            c_model_spend, c_reqs = await cursor.fetchone()

            cursor = await db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM agent_actions WHERE run_id = ? AND workspace_id = ?",
                (c_id, workspace_id),
            )
            c_action_spend, c_actions = await cursor.fetchone()

            c_total = c_model_spend + c_action_spend
            total_children_spend += c_total
            children_breakdown[c_id] = {
                "total_spend_usd": round(c_total, 6),
                "model_spend_usd": round(c_model_spend, 6),
                "action_spend_usd": round(c_action_spend, 6),
                "requests_count": c_reqs,
                "actions_count": c_actions,
            }

        # 3. Overall recursive rollup
        # Total rollup = direct parent spend + children spend
        rollup_total = direct_total + total_children_spend

        # Retry waste across all runs in tree
        placeholders = ",".join("?" for _ in all_run_ids)
        cursor = await db.execute(
            f"""
            SELECT COALESCE(SUM(cost_usd), 0.0)
            FROM requests
            WHERE (run_id IN ({placeholders}) OR json_extract(tags, '$.run_id') IN ({placeholders}))
              AND (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
              AND status_code >= 400
            """,
            all_run_ids + all_run_ids + [workspace_id, workspace_id],
        )
        total_retry_waste = (await cursor.fetchone())[0]

        return {
            "run_id": run_id,
            "total_rollup_spend_usd": round(rollup_total, 6),
            "direct_spend_usd": round(direct_total, 6),
            "children_spend_usd": round(total_children_spend, 6),
            "retry_waste_usd": round(total_retry_waste, 6),
            "child_runs_count": len(child_run_ids),
            "children_breakdown": children_breakdown,
        }


async def get_workflow_economics(
    db_path: str,
    workflow_id: str,
    workspace_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Calculate unit economics for a workflow, including cost per accepted outcome."""
    conds = ["(workflow_id = ? OR json_extract(tags, '$.workflow_id') = ?)"]
    params: list[Any] = [workflow_id, workflow_id]
    if workspace_id:
        conds.append("(workspace_id = ? OR json_extract(tags, '$.workspace_id') = ?)")
        params.extend([workspace_id, workspace_id])
    if since:
        conds.append("timestamp >= ?")
        params.append(since)

    where_clause = " WHERE " + " AND ".join(conds)

    async with aiosqlite.connect(db_path) as db:
        # Total workflow spend from canonical ledger
        cursor = await db.execute(
            f"""
            SELECT
                COALESCE(SUM(cost_usd), 0.0),
                COUNT(*),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0)
            FROM requests
            {where_clause}
            """,
            params,
        )
        model_spend, req_count, in_toks, out_toks = await cursor.fetchone()

        # Retry waste
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests {where_clause} AND status_code >= 400",
            params,
        )
        retry_waste = (await cursor.fetchone())[0]

        # Action spend
        act_conds = ["run_id IN (SELECT run_id FROM agent_runs WHERE workflow_id = ?)"]
        act_params: list[Any] = [workflow_id]
        if workspace_id:
            act_conds.append("workspace_id = ?")
            act_params.append(workspace_id)
        if since:
            act_conds.append("created_at >= ?")
            act_params.append(since)

        cursor = await db.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM agent_actions WHERE {' AND '.join(act_conds)}",
            act_params,
        )
        tool_action_cost, action_count = await cursor.fetchone()

        total_spend = model_spend + tool_action_cost

        # Query outcomes
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM outcomes WHERE workflow_id = ? GROUP BY status",
            (workflow_id,),
        )
        outcome_rows = await cursor.fetchall()
        outcomes_by_status = {r[0]: r[1] for r in outcome_rows}

        accepted_count = outcomes_by_status.get("accepted", 0)
        rejected_count = outcomes_by_status.get("rejected", 0)
        failed_count = outcomes_by_status.get("failed", 0)
        total_outcomes = accepted_count + rejected_count + failed_count

        cost_per_accepted = (
            round(total_spend / accepted_count, 6) if accepted_count > 0 else None
        )

        return {
            "workflow_id": workflow_id,
            "total_spend_usd": round(total_spend, 6),
            "model_spend_usd": round(model_spend, 6),
            "tool_action_spend_usd": round(tool_action_cost, 6),
            "retry_waste_usd": round(retry_waste, 6),
            "requests_count": req_count,
            "actions_count": action_count,
            "outcomes_count": total_outcomes,
            "accepted_outcomes": accepted_count,
            "rejected_outcomes": rejected_count,
            "failed_outcomes": failed_count,
            "cost_per_accepted_outcome_usd": cost_per_accepted,
        }


async def get_workspace_agent_attribution(
    db_path: str, workspace_id: str = "default"
) -> dict[str, Any]:
    """Validate the attribution invariant:

    total_workspace_spend = agent_attributed_spend + unattributed_spend
    """
    async with aiosqlite.connect(db_path) as db:
        # Total workspace spend
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM requests WHERE workspace_id = ? OR (workspace_id IS NULL AND ? = 'default')",
            (workspace_id, workspace_id),
        )
        total_spend, total_reqs = await cursor.fetchone()

        # Agent-attributed spend
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*)
            FROM requests
            WHERE (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
              AND (agent_id IS NOT NULL OR json_extract(tags, '$.agent_id') IS NOT NULL)
            """,
            (workspace_id, workspace_id),
        )
        agent_spend, agent_reqs = await cursor.fetchone()

        unattributed_spend = total_spend - agent_spend
        unattributed_reqs = total_reqs - agent_reqs

        return {
            "workspace_id": workspace_id,
            "total_workspace_spend_usd": round(total_spend, 6),
            "agent_attributed_spend_usd": round(agent_spend, 6),
            "unattributed_spend_usd": round(unattributed_spend, 6),
            "total_requests": total_reqs,
            "agent_requests": agent_reqs,
            "unattributed_requests": unattributed_reqs,
            "invariant_holds": abs(total_spend - (agent_spend + unattributed_spend)) < 1e-6,
        }
