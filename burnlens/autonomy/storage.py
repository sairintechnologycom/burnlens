"""Phase 10: BL-AE-010 Controlled Autonomy Storage.

Persists autonomous optimization plans, audit chains, and emergency kill switches
in SQLite with strict workspace isolation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.autonomy.models import (
    AutonomousOptimizationPlan,
    CanaryStatus,
)

logger = logging.getLogger(__name__)


class AutonomyStorage:
    """Async SQLite storage for closed-loop autonomous plans and audit chains."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_autonomy_schema(self) -> None:
        """Create autonomy tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomous_plans (
                    plan_id                 TEXT PRIMARY KEY,
                    workspace_id            TEXT NOT NULL,
                    agent_id                TEXT NOT NULL,
                    recommendation_id       TEXT NOT NULL,
                    category                TEXT NOT NULL,
                    target_config           TEXT NOT NULL DEFAULT '{}',
                    canary_percentage       REAL NOT NULL DEFAULT 10.0,
                    max_canary_spend_usd    REAL NOT NULL DEFAULT 5.0,
                    canary_status           TEXT NOT NULL DEFAULT 'PROPOSED',
                    is_kill_switched        INTEGER NOT NULL DEFAULT 0,
                    fingerprint             TEXT NOT NULL,
                    created_at              TEXT NOT NULL,
                    updated_at              TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_auton_plans_ws ON autonomous_plans (workspace_id, canary_status)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomous_audit_trail (
                    audit_id                TEXT PRIMARY KEY,
                    plan_id                 TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    stage                   TEXT NOT NULL,
                    action                  TEXT NOT NULL,
                    details                 TEXT NOT NULL DEFAULT '{}',
                    timestamp               TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_auton_audit_plan ON autonomous_audit_trail (plan_id, timestamp)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_kill_switches (
                    workspace_id            TEXT PRIMARY KEY,
                    is_disabled             INTEGER NOT NULL DEFAULT 0,
                    reason                  TEXT,
                    disabled_by             TEXT,
                    updated_at              TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def save_plan(self, plan: AutonomousOptimizationPlan) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO autonomous_plans (
                    plan_id, workspace_id, agent_id, recommendation_id, category,
                    target_config, canary_percentage, max_canary_spend_usd, canary_status,
                    is_kill_switched, fingerprint, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.workspace_id,
                    plan.agent_id,
                    plan.recommendation_id,
                    plan.category,
                    json.dumps(plan.target_config),
                    plan.canary_percentage,
                    plan.max_canary_spend_usd,
                    plan.canary_status.value,
                    1 if plan.is_kill_switched else 0,
                    plan.fingerprint,
                    plan.created_at.isoformat(),
                    now_str,
                ),
            )
            await db.commit()

    async def update_plan_status(self, plan_id: str, status: CanaryStatus) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE autonomous_plans SET canary_status = ?, updated_at = ? WHERE plan_id = ?",
                (status.value, now_str, plan_id),
            )
            await db.commit()

    async def record_audit_event(
        self, audit_id: str, plan_id: str, workspace_id: str, stage: str, action: str, details: dict[str, Any]
    ) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO autonomous_audit_trail (
                    audit_id, plan_id, workspace_id, stage, action, details, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, plan_id, workspace_id, stage, action, json.dumps(details), now_str),
            )
            await db.commit()

    async def get_audit_trail(self, plan_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT audit_id, plan_id, workspace_id, stage, action, details, timestamp
                FROM autonomous_audit_trail
                WHERE plan_id = ?
                ORDER BY timestamp ASC
                """,
                (plan_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "audit_id": row[0],
                    "plan_id": row[1],
                    "workspace_id": row[2],
                    "stage": row[3],
                    "action": row[4],
                    "details": json.loads(row[5] or "{}"),
                    "timestamp": row[6],
                }
                for row in rows
            ]

    async def set_workspace_kill_switch(self, workspace_id: str, is_disabled: bool, reason: str, disabled_by: str) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO workspace_kill_switches (
                    workspace_id, is_disabled, reason, disabled_by, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (workspace_id, 1 if is_disabled else 0, reason, disabled_by, now_str),
            )
            await db.commit()

    async def is_workspace_kill_switched(self, workspace_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT is_disabled FROM workspace_kill_switches WHERE workspace_id = ?",
                (workspace_id,),
            )
            row = await cursor.fetchone()
            return bool(row[0]) if row else False
