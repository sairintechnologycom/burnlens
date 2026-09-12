"""Phase 5: BL-AE-005 Governance Shadow Evaluation Engine.

Evaluates incoming agent actions against versioned policy rules.
In SHADOW mode:
- Computes what the decision WOULD be (ALLOW, DENY, REQUIRE_APPROVAL, BUDGET_EXCEEDED)
- Records the decision in policy_evaluations audit log with full provenance
- NEVER blocks or halts the action (effective_action_taken = "ALLOWED_BY_SHADOW_MODE")
- Enforces strict tenant isolation and fail-safe defaults
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.governance.models import (
    ActionType,
    EnforcementMode,
    PolicyDecision,
    PolicyEvaluationRecord,
    PolicyRule,
    RiskClassification,
)

logger = logging.getLogger(__name__)

# Default standard baseline policies
DEFAULT_BASELINE_POLICIES = [
    PolicyRule(
        policy_id="pol-default-read",
        name="Allow Repository Reads",
        workspace_id="*",
        action_type=ActionType.READ_REPOSITORY.value,
        risk_level=RiskClassification.LOW,
        decision_if_matched=PolicyDecision.ALLOW,
        condition_expression="true",
    ),
    PolicyRule(
        policy_id="pol-default-branch",
        name="Allow Branch Creation",
        workspace_id="*",
        action_type=ActionType.CREATE_BRANCH.value,
        risk_level=RiskClassification.LOW,
        decision_if_matched=PolicyDecision.ALLOW,
        condition_expression="true",
    ),
    PolicyRule(
        policy_id="pol-default-open-pr",
        name="Allow Open Pull Request",
        workspace_id="*",
        action_type=ActionType.OPEN_PR.value,
        risk_level=RiskClassification.LOW,
        decision_if_matched=PolicyDecision.ALLOW,
        condition_expression="true",
    ),
    PolicyRule(
        policy_id="pol-default-merge-pr",
        name="Require Approval for Main/Prod PR Merges",
        workspace_id="*",
        action_type=ActionType.MERGE_PR.value,
        risk_level=RiskClassification.HIGH,
        decision_if_matched=PolicyDecision.REQUIRE_APPROVAL,
        condition_expression="target_branch in ['main', 'master', 'production']",
        target_pattern="*",
    ),
    PolicyRule(
        policy_id="pol-default-iam",
        name="Deny IAM Modification",
        workspace_id="*",
        action_type=ActionType.CHANGE_IAM.value,
        risk_level=RiskClassification.CRITICAL,
        decision_if_matched=PolicyDecision.DENY,
        condition_expression="true",
    ),
    PolicyRule(
        policy_id="pol-default-budget-cap",
        name="Require Approval If Task Cost > $10",
        workspace_id="*",
        action_type="*",
        risk_level=RiskClassification.MEDIUM,
        decision_if_matched=PolicyDecision.REQUIRE_APPROVAL,
        max_cost_usd=10.0,
        condition_expression="cost > 10.0",
    ),
]


class PolicyStorage:
    """Storage management for policy rules and evaluation records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_governance_schema(self) -> None:
        """Create governance tables if they do not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            # Policy rules table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_rules (
                    policy_id           TEXT PRIMARY KEY,
                    name                TEXT NOT NULL,
                    workspace_id        TEXT NOT NULL DEFAULT 'default',
                    action_type         TEXT NOT NULL DEFAULT '*',
                    risk_level          TEXT NOT NULL DEFAULT 'MEDIUM',
                    decision_if_matched TEXT NOT NULL DEFAULT 'REQUIRE_APPROVAL',
                    condition_expression TEXT NOT NULL DEFAULT 'true',
                    max_cost_usd        REAL,
                    target_pattern      TEXT NOT NULL DEFAULT '*',
                    version             INTEGER NOT NULL DEFAULT 1,
                    is_active           INTEGER NOT NULL DEFAULT 1,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_rules_ws ON policy_rules (workspace_id, is_active)"
            )

            # Policy evaluations audit table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_evaluations (
                    evaluation_id          TEXT PRIMARY KEY,
                    workspace_id           TEXT NOT NULL,
                    agent_id               TEXT NOT NULL,
                    task_id                TEXT,
                    run_id                 TEXT,
                    action_type            TEXT NOT NULL,
                    target                 TEXT NOT NULL,
                    enforcement_mode       TEXT NOT NULL,
                    decision               TEXT NOT NULL,
                    effective_action_taken TEXT NOT NULL,
                    matched_policy_id      TEXT,
                    reason                 TEXT NOT NULL,
                    cost_usd               REAL NOT NULL DEFAULT 0.0,
                    context_metadata       TEXT NOT NULL DEFAULT '{}',
                    evaluated_at           TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_eval_ws_time ON policy_evaluations (workspace_id, evaluated_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_eval_agent ON policy_evaluations (agent_id)"
            )

            # Approvals table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id            TEXT PRIMARY KEY,
                    evaluation_id          TEXT NOT NULL,
                    workspace_id           TEXT NOT NULL,
                    status                 TEXT NOT NULL DEFAULT 'pending',
                    approver               TEXT,
                    reason                 TEXT NOT NULL DEFAULT '',
                    created_at             TEXT NOT NULL,
                    resolved_at            TEXT
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_eval ON approvals (evaluation_id)"
            )

            # Seed default policies if table is empty
            cursor = await db.execute("SELECT COUNT(*) FROM policy_rules")
            count = (await cursor.fetchone())[0]
            if count == 0:
                for pol in DEFAULT_BASELINE_POLICIES:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO policy_rules (
                            policy_id, name, workspace_id, action_type, risk_level,
                            decision_if_matched, condition_expression, max_cost_usd,
                            target_pattern, version, is_active, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pol.policy_id,
                            pol.name,
                            pol.workspace_id,
                            pol.action_type,
                            pol.risk_level.value,
                            pol.decision_if_matched.value,
                            pol.condition_expression,
                            pol.max_cost_usd,
                            pol.target_pattern,
                            pol.version,
                            1 if pol.is_active else 0,
                            pol.created_at.isoformat(),
                            pol.updated_at.isoformat(),
                        ),
                    )
            await db.commit()

    async def save_policy_rule(self, rule: PolicyRule) -> str:
        """Insert or update a policy rule with version bumping."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO policy_rules (
                    policy_id, name, workspace_id, action_type, risk_level,
                    decision_if_matched, condition_expression, max_cost_usd,
                    target_pattern, version, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    name = excluded.name,
                    workspace_id = excluded.workspace_id,
                    action_type = excluded.action_type,
                    risk_level = excluded.risk_level,
                    decision_if_matched = excluded.decision_if_matched,
                    condition_expression = excluded.condition_expression,
                    max_cost_usd = excluded.max_cost_usd,
                    target_pattern = excluded.target_pattern,
                    version = policy_rules.version + 1,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    rule.policy_id,
                    rule.name,
                    rule.workspace_id,
                    rule.action_type,
                    rule.risk_level.value,
                    rule.decision_if_matched.value,
                    rule.condition_expression,
                    rule.max_cost_usd,
                    rule.target_pattern,
                    rule.version,
                    1 if rule.is_active else 0,
                    rule.created_at.isoformat(),
                    rule.updated_at.isoformat(),
                ),
            )
            await db.commit()
        return rule.policy_id

    async def get_active_rules(self, workspace_id: str) -> list[PolicyRule]:
        """Fetch active policy rules for a workspace + global wildcard '*' rules."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT policy_id, name, workspace_id, action_type, risk_level,
                       decision_if_matched, condition_expression, max_cost_usd,
                       target_pattern, version, is_active, created_at, updated_at
                FROM policy_rules
                WHERE is_active = 1 AND (workspace_id = ? OR workspace_id = '*' OR (workspace_id = 'default' AND ? = 'default'))
                ORDER BY version DESC
                """,
                (workspace_id, workspace_id),
            )
            rows = await cursor.fetchall()

        rules = []
        for r in rows:
            rules.append(
                PolicyRule(
                    policy_id=r[0],
                    name=r[1],
                    workspace_id=r[2],
                    action_type=r[3],
                    risk_level=RiskClassification(r[4]),
                    decision_if_matched=PolicyDecision(r[5]),
                    condition_expression=r[6],
                    max_cost_usd=r[7],
                    target_pattern=r[8],
                    version=r[9],
                    is_active=bool(r[10]),
                    created_at=datetime.fromisoformat(r[11]),
                    updated_at=datetime.fromisoformat(r[12]),
                )
            )
        return rules

    async def record_evaluation(self, record: PolicyEvaluationRecord) -> None:
        """Persist policy evaluation result in audit log."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO policy_evaluations (
                    evaluation_id, workspace_id, agent_id, task_id, run_id,
                    action_type, target, enforcement_mode, decision,
                    effective_action_taken, matched_policy_id, reason,
                    cost_usd, context_metadata, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.evaluation_id,
                    record.workspace_id,
                    record.agent_id,
                    record.task_id,
                    record.run_id,
                    record.action_type,
                    record.target,
                    record.enforcement_mode.value,
                    record.decision.value,
                    record.effective_action_taken,
                    record.matched_policy_id,
                    record.reason,
                    record.cost_usd,
                    json.dumps(record.context_metadata),
                    record.evaluated_at.isoformat(),
                ),
            )
            await db.commit()


class GovernanceEngine:
    """Core decisioning engine evaluating policies in Shadow Mode."""

    def __init__(
        self,
        db_path: str,
        mode: EnforcementMode = EnforcementMode.SHADOW,
    ) -> None:
        self.db_path = db_path
        self.mode = mode
        self.storage = PolicyStorage(db_path)

    async def evaluate_action(
        self,
        workspace_id: str,
        agent_id: str,
        action_type: str,
        target: str = "",
        task_id: str | None = None,
        run_id: str | None = None,
        cost_usd: float = 0.0,
        context_metadata: dict[str, Any] | None = None,
    ) -> PolicyEvaluationRecord:
        """Evaluate an action against active policies.

        In SHADOW mode:
        Decision is computed accurately, but effective_action_taken is
        ALLOWED_BY_SHADOW_MODE so existing workloads are never interrupted.
        """
        metadata = context_metadata or {}
        active_rules = await self.storage.get_active_rules(workspace_id)

        # Match policy rules
        matched_rule: PolicyRule | None = None
        computed_decision = PolicyDecision.ALLOW
        reason = "Default allow: no restricting policy matched"

        # Prioritize DENY > REQUIRE_APPROVAL > ALLOW
        candidates: list[tuple[PolicyRule, PolicyDecision, str]] = []

        for rule in active_rules:
            # Match action type
            if rule.action_type != "*" and rule.action_type.lower() != action_type.lower():
                continue

            # Match target pattern if specified
            if rule.target_pattern != "*" and not fnmatch.fnmatch(target, rule.target_pattern):
                continue

            # Check budget / cost threshold if configured on rule
            if rule.max_cost_usd is not None:
                if cost_usd > rule.max_cost_usd:
                    candidates.append((
                        rule,
                        PolicyDecision.REQUIRE_APPROVAL,
                        f"Action cost ${cost_usd:.4f} exceeds policy max ${rule.max_cost_usd:.4f}",
                    ))
                continue

            # Check condition expressions
            if rule.action_type == ActionType.MERGE_PR.value:
                target_branch = metadata.get("target_branch", target)
                if target_branch in ("main", "master", "production"):
                    candidates.append((
                        rule,
                        rule.decision_if_matched,
                        f"Merge to protected branch '{target_branch}' requires approval",
                    ))
                    continue

            if rule.action_type == ActionType.CHANGE_IAM.value:
                candidates.append((
                    rule,
                    rule.decision_if_matched,
                    "Direct IAM modifications by autonomous agents are disallowed",
                ))
                continue

            # If rule matched general criteria
            candidates.append((
                rule,
                rule.decision_if_matched,
                f"Matched policy '{rule.name}' ({rule.policy_id})",
            ))

        if candidates:
            # Sort order: DENY (highest priority) -> REQUIRE_APPROVAL -> BUDGET_EXCEEDED -> ALLOW
            def sort_priority(item: tuple[PolicyRule, PolicyDecision, str]) -> int:
                dec = item[1]
                if dec == PolicyDecision.DENY:
                    return 0
                if dec == PolicyDecision.REQUIRE_APPROVAL:
                    return 1
                if dec == PolicyDecision.BUDGET_EXCEEDED:
                    return 2
                return 3

            candidates.sort(key=sort_priority)
            matched_rule, computed_decision, reason = candidates[0]

        # Determine effective action based on enforcement mode
        eval_id = f"eval_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        if self.mode in (EnforcementMode.OBSERVE, EnforcementMode.SHADOW):
            # In shadow mode, we never block production workloads
            effective_action = "ALLOWED_BY_SHADOW_MODE"
        elif self.mode == EnforcementMode.APPROVAL_REQUIRED:
            if computed_decision in (PolicyDecision.REQUIRE_APPROVAL, PolicyDecision.DENY):
                effective_action = "BLOCKED_PENDING_APPROVAL"
            else:
                effective_action = "PROCEED"
        elif self.mode == EnforcementMode.ENFORCED:
            effective_action = "DENIED" if computed_decision == PolicyDecision.DENY else "PROCEED"
        else:  # AUTONOMOUS
            effective_action = "AUTONOMOUS_EXECUTE"

        record = PolicyEvaluationRecord(
            evaluation_id=eval_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            action_type=action_type,
            target=target,
            enforcement_mode=self.mode,
            decision=computed_decision,
            effective_action_taken=effective_action,
            matched_policy_id=matched_rule.policy_id if matched_rule else None,
            reason=reason,
            cost_usd=cost_usd,
            context_metadata=metadata,
            evaluated_at=now,
        )

        await self.storage.record_evaluation(record)
        return record

    async def get_shadow_evaluation_summary(
        self, workspace_id: str
    ) -> dict[str, Any]:
        """Aggregate shadow evaluation predictions to analyze accuracy and false positive/negative rates."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT decision, COUNT(*)
                FROM policy_evaluations
                WHERE workspace_id = ?
                GROUP BY decision
                """,
                (workspace_id,),
            )
            rows = await cursor.fetchall()

        decision_counts = {r[0]: r[1] for r in rows}
        total_evaluations = sum(decision_counts.values())

        return {
            "workspace_id": workspace_id,
            "enforcement_mode": self.mode.value,
            "total_evaluations": total_evaluations,
            "would_allow": decision_counts.get(PolicyDecision.ALLOW.value, 0),
            "would_require_approval": decision_counts.get(PolicyDecision.REQUIRE_APPROVAL.value, 0),
            "would_deny": decision_counts.get(PolicyDecision.DENY.value, 0),
            "would_flag_budget_exceeded": decision_counts.get(PolicyDecision.BUDGET_EXCEEDED.value, 0),
            "distribution_percentage": {
                k: round((v / total_evaluations) * 100, 2) if total_evaluations > 0 else 0.0
                for k, v in decision_counts.items()
            },
        }
