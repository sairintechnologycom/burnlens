"""Phase 9: BL-AE-009 Agent Trust & Earned Autonomy Data Models.

Defines:
- AutonomyLevel: RESTRICTED, STANDARD, EARNED_AUTONOMY
- AgentTrustProfile: Deterministic, explainable multi-signal trust scoring
- AutonomyEligibilityCheck: Granular per-action eligibility evaluation
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AutonomyLevel(str, Enum):
    """Graduated autonomy tiers earned through demonstrated reliability."""

    RESTRICTED = "RESTRICTED"              # Score < 50 or sparse history: all non-read actions require human approval
    STANDARD = "STANDARD"                  # Score 50-79: standard supervised execution
    EARNED_AUTONOMY = "EARNED_AUTONOMY"    # Score >= 80: eligible for autonomous execution on low-risk, bounded actions


HIGH_RISK_ACTIONS = frozenset({
    "change_iam",
    "modify_security_policy",
    "drop_database",
    "direct_push_main",
    "direct_push_master",
    "auto_merge_production",
    "secret_access",
})


@dataclass
class AgentTrustProfile:
    """Deterministic trust profile evaluated from historical ledger and audit evidence."""

    agent_id: str
    workspace_id: str
    trust_score: float  # 0.0 to 100.0
    task_success_rate: float
    accepted_outcome_rate: float
    rollback_rate: float
    policy_violation_rate: float
    waste_ratio: float
    total_tasks: int
    total_spend_usd: float
    autonomy_level: AutonomyLevel
    is_sparse_history: bool
    breakdown: dict[str, Any] = field(default_factory=dict)
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint of computed trust metrics."""
        raw = (
            f"{self.agent_id}:{self.workspace_id}:{self.trust_score:.2f}:{self.total_tasks}:"
            f"{self.task_success_rate:.4f}:{self.accepted_outcome_rate:.4f}:{self.rollback_rate:.4f}:"
            f"{self.policy_violation_rate:.4f}:{self.waste_ratio:.4f}:{self.autonomy_level.value}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "trust_score": self.trust_score,
            "autonomy_level": self.autonomy_level.value,
            "task_success_rate": self.task_success_rate,
            "accepted_outcome_rate": self.accepted_outcome_rate,
            "rollback_rate": self.rollback_rate,
            "policy_violation_rate": self.policy_violation_rate,
            "waste_ratio": self.waste_ratio,
            "total_tasks": self.total_tasks,
            "total_spend_usd": self.total_spend_usd,
            "is_sparse_history": self.is_sparse_history,
            "breakdown": self.breakdown,
            "calculated_at": self.calculated_at.isoformat(),
        }


@dataclass
class AutonomyEligibilityCheck:
    """Result of evaluating whether an action is eligible for autonomous execution."""

    agent_id: str
    workspace_id: str
    action_type: str
    estimated_cost_usd: float
    is_autonomous_eligible: bool
    requires_human_approval: bool
    trust_score: float
    autonomy_level: AutonomyLevel
    reason: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "action_type": self.action_type,
            "estimated_cost_usd": self.estimated_cost_usd,
            "is_autonomous_eligible": self.is_autonomous_eligible,
            "requires_human_approval": self.requires_human_approval,
            "trust_score": self.trust_score,
            "autonomy_level": self.autonomy_level.value,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
