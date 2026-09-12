"""Phase 7: BL-AE-007 Runtime Guardrails Storage.

Provides persistent SQLite storage for:
- Workspace guardrail policies
- Task runtime metrics & lifecycle states (ACTIVE, PAUSED, STOPPED)
- Guardrail decision audit logs
- Deduplication of incoming telemetry events
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.guardrails.models import (
    FailSafeMode,
    GuardrailDecision,
    GuardrailDecisionType,
    GuardrailFailureType,
    GuardrailPolicy,
    TaskLifecycleState,
)

logger = logging.getLogger(__name__)


class GuardrailStorage:
    """Async SQLite storage for guardrails policies, task state, and decision logs."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_guardrail_schema(self) -> None:
        """Create guardrail tables if not existing."""
        async with aiosqlite.connect(self.db_path) as db:
            # Policies
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS guardrail_policies (
                    policy_id                   TEXT PRIMARY KEY,
                    workspace_id                TEXT NOT NULL,
                    name                        TEXT NOT NULL,
                    max_retries                 INTEGER NOT NULL DEFAULT 3,
                    hard_budget_usd             REAL NOT NULL DEFAULT 25.0,
                    max_consecutive_tool_errors INTEGER NOT NULL DEFAULT 3,
                    max_task_requests           INTEGER NOT NULL DEFAULT 50,
                    forbidden_actions           TEXT NOT NULL DEFAULT '[]',
                    fail_safe_mode              TEXT NOT NULL DEFAULT 'FAIL_CLOSED',
                    version                     INTEGER NOT NULL DEFAULT 1,
                    is_active                   INTEGER NOT NULL DEFAULT 1,
                    created_at                  TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_guardrail_pol_ws ON guardrail_policies (workspace_id, is_active)"
            )

            # Task runtime state
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS task_guardrail_state (
                    task_id                     TEXT PRIMARY KEY,
                    workspace_id                TEXT NOT NULL,
                    agent_id                    TEXT NOT NULL,
                    state                       TEXT NOT NULL DEFAULT 'ACTIVE',
                    total_cost_usd              REAL NOT NULL DEFAULT 0.0,
                    retry_count                 INTEGER NOT NULL DEFAULT 0,
                    consecutive_tool_errors     INTEGER NOT NULL DEFAULT 0,
                    request_count               INTEGER NOT NULL DEFAULT 0,
                    paused_reason               TEXT,
                    paused_at                   TEXT,
                    resumed_at                  TEXT,
                    resumed_by                  TEXT,
                    stopped_reason              TEXT,
                    updated_at                  TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_state_ws ON task_guardrail_state (workspace_id, state)"
            )

            # Guardrail decisions audit
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS guardrail_decisions (
                    decision_id                 TEXT PRIMARY KEY,
                    workspace_id                TEXT NOT NULL,
                    agent_id                    TEXT NOT NULL,
                    task_id                     TEXT NOT NULL,
                    decision                    TEXT NOT NULL,
                    failure_type                TEXT NOT NULL,
                    reason                      TEXT NOT NULL,
                    current_metrics             TEXT NOT NULL DEFAULT '{}',
                    threshold                   TEXT NOT NULL DEFAULT '{}',
                    evaluated_at                TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_ws_time ON guardrail_decisions (workspace_id, evaluated_at)"
            )

            # Telemetry events deduplication table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS guardrail_telemetry_dedup (
                    event_id                    TEXT PRIMARY KEY,
                    workspace_id                TEXT NOT NULL,
                    task_id                     TEXT NOT NULL,
                    ingested_at                 TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def save_policy(self, policy: GuardrailPolicy) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO guardrail_policies (
                    policy_id, workspace_id, name, max_retries, hard_budget_usd,
                    max_consecutive_tool_errors, max_task_requests, forbidden_actions,
                    fail_safe_mode, version, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.policy_id,
                    policy.workspace_id,
                    policy.name,
                    policy.max_retries,
                    policy.hard_budget_usd,
                    policy.max_consecutive_tool_errors,
                    policy.max_task_requests,
                    json.dumps(policy.forbidden_actions),
                    policy.fail_safe_mode.value,
                    policy.version,
                    1 if policy.is_active else 0,
                    policy.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_policy(self, workspace_id: str) -> GuardrailPolicy | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT policy_id, workspace_id, name, max_retries, hard_budget_usd,
                       max_consecutive_tool_errors, max_task_requests, forbidden_actions,
                       fail_safe_mode, version, is_active, created_at
                FROM guardrail_policies
                WHERE workspace_id = ? AND is_active = 1
                ORDER BY version DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            return GuardrailPolicy(
                policy_id=row[0],
                workspace_id=row[1],
                name=row[2],
                max_retries=row[3],
                hard_budget_usd=row[4],
                max_consecutive_tool_errors=row[5],
                max_task_requests=row[6],
                forbidden_actions=json.loads(row[7] or "[]"),
                fail_safe_mode=FailSafeMode(row[8]),
                version=row[9],
                is_active=bool(row[10]),
                created_at=datetime.fromisoformat(row[11]),
            )

    async def is_event_duplicate(self, event_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM guardrail_telemetry_dedup WHERE event_id = ?",
                (event_id,),
            )
            return (await cursor.fetchone()) is not None

    async def record_event_ingestion(self, event_id: str, workspace_id: str, task_id: str) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO guardrail_telemetry_dedup (event_id, workspace_id, task_id, ingested_at) VALUES (?, ?, ?, ?)",
                (event_id, workspace_id, task_id, now_str),
            )
            await db.commit()

    async def get_or_create_task_state(self, task_id: str, workspace_id: str, agent_id: str) -> dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT task_id, workspace_id, agent_id, state, total_cost_usd,
                       retry_count, consecutive_tool_errors, request_count,
                       paused_reason, paused_at, resumed_at, resumed_by, stopped_reason
                FROM task_guardrail_state
                WHERE task_id = ? AND workspace_id = ?
                """,
                (task_id, workspace_id),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "task_id": row[0],
                    "workspace_id": row[1],
                    "agent_id": row[2],
                    "state": TaskLifecycleState(row[3]),
                    "total_cost_usd": row[4],
                    "retry_count": row[5],
                    "consecutive_tool_errors": row[6],
                    "request_count": row[7],
                    "paused_reason": row[8],
                    "paused_at": row[9],
                    "resumed_at": row[10],
                    "resumed_by": row[11],
                    "stopped_reason": row[12],
                }

            # Create default active state
            await db.execute(
                """
                INSERT OR IGNORE INTO task_guardrail_state (
                    task_id, workspace_id, agent_id, state, total_cost_usd,
                    retry_count, consecutive_tool_errors, request_count, updated_at
                ) VALUES (?, ?, ?, 'ACTIVE', 0.0, 0, 0, 0, ?)
                """,
                (task_id, workspace_id, agent_id, now_str),
            )
            await db.commit()
            return {
                "task_id": task_id,
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "state": TaskLifecycleState.ACTIVE,
                "total_cost_usd": 0.0,
                "retry_count": 0,
                "consecutive_tool_errors": 0,
                "request_count": 0,
                "paused_reason": None,
                "paused_at": None,
                "resumed_at": None,
                "resumed_by": None,
                "stopped_reason": None,
            }

    async def update_task_metrics(
        self,
        task_id: str,
        workspace_id: str,
        cost_increment: float,
        is_retry: bool,
        is_tool_error: bool,
        reset_tool_errors: bool = False,
    ) -> dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            # Atomic update
            retry_inc = 1 if is_retry else 0
            if reset_tool_errors:
                err_expr = "0"
            elif is_tool_error:
                err_expr = "consecutive_tool_errors + 1"
            else:
                err_expr = "consecutive_tool_errors"

            await db.execute(
                f"""
                UPDATE task_guardrail_state
                SET total_cost_usd = total_cost_usd + ?,
                    retry_count = retry_count + ?,
                    consecutive_tool_errors = {err_expr},
                    request_count = request_count + 1,
                    updated_at = ?
                WHERE task_id = ? AND workspace_id = ?
                """,
                (cost_increment, retry_inc, now_str, task_id, workspace_id),
            )
            await db.commit()

        return await self.get_or_create_task_state(task_id, workspace_id, "")

    async def set_task_state(
        self,
        task_id: str,
        workspace_id: str,
        state: TaskLifecycleState,
        reason: str | None = None,
        operator: str | None = None,
    ) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            if state == TaskLifecycleState.PAUSED:
                await db.execute(
                    """
                    UPDATE task_guardrail_state
                    SET state = 'PAUSED', paused_reason = ?, paused_at = ?, updated_at = ?
                    WHERE task_id = ? AND workspace_id = ?
                    """,
                    (reason, now_str, now_str, task_id, workspace_id),
                )
            elif state == TaskLifecycleState.STOPPED:
                await db.execute(
                    """
                    UPDATE task_guardrail_state
                    SET state = 'STOPPED', stopped_reason = ?, updated_at = ?
                    WHERE task_id = ? AND workspace_id = ?
                    """,
                    (reason, now_str, task_id, workspace_id),
                )
            elif state == TaskLifecycleState.ACTIVE:
                # Resume task
                await db.execute(
                    """
                    UPDATE task_guardrail_state
                    SET state = 'ACTIVE', resumed_at = ?, resumed_by = ?,
                        consecutive_tool_errors = 0, retry_count = 0, updated_at = ?
                    WHERE task_id = ? AND workspace_id = ?
                    """,
                    (now_str, operator or "human_operator", now_str, task_id, workspace_id),
                )
            await db.commit()

    async def record_decision(self, decision: GuardrailDecision) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO guardrail_decisions (
                    decision_id, workspace_id, agent_id, task_id, decision,
                    failure_type, reason, current_metrics, threshold, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.workspace_id,
                    decision.agent_id,
                    decision.task_id,
                    decision.decision.value,
                    decision.failure_type.value,
                    decision.reason,
                    json.dumps(decision.current_metrics),
                    json.dumps(decision.threshold),
                    decision.evaluated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_decisions(self, task_id: str, workspace_id: str) -> list[GuardrailDecision]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT decision_id, workspace_id, agent_id, task_id, decision,
                       failure_type, reason, current_metrics, threshold, evaluated_at
                FROM guardrail_decisions
                WHERE task_id = ? AND workspace_id = ?
                ORDER BY evaluated_at ASC
                """,
                (task_id, workspace_id),
            )
            rows = await cursor.fetchall()
            return [
                GuardrailDecision(
                    decision_id=row[0],
                    workspace_id=row[1],
                    agent_id=row[2],
                    task_id=row[3],
                    decision=GuardrailDecisionType(row[4]),
                    failure_type=GuardrailFailureType(row[5]),
                    reason=row[6],
                    current_metrics=json.loads(row[7] or "{}"),
                    threshold=json.loads(row[8] or "{}"),
                    evaluated_at=datetime.fromisoformat(row[9]),
                )
                for row in rows
            ]
