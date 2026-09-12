"""Phase 9: BL-AE-009 Agent Trust Storage.

Persists agent trust profiles and autonomy eligibility decisions in SQLite
with tenant isolation and audit history.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.trust.models import (
    AgentTrustProfile,
    AutonomyEligibilityCheck,
    AutonomyLevel,
)

logger = logging.getLogger(__name__)


class TrustStorage:
    """Async SQLite storage for agent trust profiles and eligibility audits."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_trust_schema(self) -> None:
        """Create trust tables if not existing."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_trust_profiles (
                    agent_id                    TEXT NOT NULL,
                    workspace_id                TEXT NOT NULL,
                    trust_score                 REAL NOT NULL,
                    autonomy_level              TEXT NOT NULL,
                    task_success_rate           REAL NOT NULL,
                    accepted_outcome_rate       REAL NOT NULL,
                    rollback_rate               REAL NOT NULL,
                    policy_violation_rate       REAL NOT NULL,
                    waste_ratio                 REAL NOT NULL,
                    total_tasks                 INTEGER NOT NULL,
                    total_spend_usd             REAL NOT NULL,
                    is_sparse_history           INTEGER NOT NULL,
                    breakdown                   TEXT NOT NULL DEFAULT '{}',
                    fingerprint                 TEXT NOT NULL,
                    calculated_at               TEXT NOT NULL,
                    PRIMARY KEY (agent_id, workspace_id)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_trust_profiles_ws ON agent_trust_profiles (workspace_id, trust_score)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomy_eligibility_audits (
                    audit_id                    TEXT PRIMARY KEY,
                    agent_id                    TEXT NOT NULL,
                    workspace_id                TEXT NOT NULL,
                    action_type                 TEXT NOT NULL,
                    estimated_cost_usd          REAL NOT NULL,
                    is_autonomous_eligible      INTEGER NOT NULL,
                    requires_human_approval     INTEGER NOT NULL,
                    trust_score                 REAL NOT NULL,
                    autonomy_level              TEXT NOT NULL,
                    reason                      TEXT NOT NULL,
                    evaluated_at                TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_autonomy_audits_ws_time ON autonomy_eligibility_audits (workspace_id, evaluated_at)"
            )
            await db.commit()

    async def save_profile(self, profile: AgentTrustProfile) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO agent_trust_profiles (
                    agent_id, workspace_id, trust_score, autonomy_level, task_success_rate,
                    accepted_outcome_rate, rollback_rate, policy_violation_rate, waste_ratio,
                    total_tasks, total_spend_usd, is_sparse_history, breakdown, fingerprint, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.agent_id,
                    profile.workspace_id,
                    profile.trust_score,
                    profile.autonomy_level.value,
                    profile.task_success_rate,
                    profile.accepted_outcome_rate,
                    profile.rollback_rate,
                    profile.policy_violation_rate,
                    profile.waste_ratio,
                    profile.total_tasks,
                    profile.total_spend_usd,
                    1 if profile.is_sparse_history else 0,
                    json.dumps(profile.breakdown),
                    profile.fingerprint,
                    profile.calculated_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_profile(self, agent_id: str, workspace_id: str) -> AgentTrustProfile | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT agent_id, workspace_id, trust_score, autonomy_level, task_success_rate,
                       accepted_outcome_rate, rollback_rate, policy_violation_rate, waste_ratio,
                       total_tasks, total_spend_usd, is_sparse_history, breakdown, fingerprint, calculated_at
                FROM agent_trust_profiles
                WHERE agent_id = ? AND workspace_id = ?
                """,
                (agent_id, workspace_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            return AgentTrustProfile(
                agent_id=row[0],
                workspace_id=row[1],
                trust_score=row[2],
                autonomy_level=AutonomyLevel(row[3]),
                task_success_rate=row[4],
                accepted_outcome_rate=row[5],
                rollback_rate=row[6],
                policy_violation_rate=row[7],
                waste_ratio=row[8],
                total_tasks=row[9],
                total_spend_usd=row[10],
                is_sparse_history=bool(row[11]),
                breakdown=json.loads(row[12] or "{}"),
                calculated_at=datetime.fromisoformat(row[14]),
            )

    async def record_eligibility_audit(self, audit_id: str, check: AutonomyEligibilityCheck) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO autonomy_eligibility_audits (
                    audit_id, agent_id, workspace_id, action_type, estimated_cost_usd,
                    is_autonomous_eligible, requires_human_approval, trust_score,
                    autonomy_level, reason, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    check.agent_id,
                    check.workspace_id,
                    check.action_type,
                    check.estimated_cost_usd,
                    1 if check.is_autonomous_eligible else 0,
                    1 if check.requires_human_approval else 0,
                    check.trust_score,
                    check.autonomy_level.value,
                    check.reason,
                    check.evaluated_at.isoformat(),
                ),
            )
            await db.commit()
