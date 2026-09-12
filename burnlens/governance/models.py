"""Phase 5: BL-AE-005 Governance Foundation Data Models.

Defines:
- EnforcementMode: OBSERVE, SHADOW, APPROVAL_REQUIRED, ENFORCED, AUTONOMOUS
- PolicyDecision: ALLOW, DENY, REQUIRE_APPROVAL, BUDGET_EXCEEDED
- RiskClassification: LOW, MEDIUM, HIGH, CRITICAL
- ActionType: READ, CREATE_BRANCH, OPEN_PR, MERGE_PR, EXECUTE_TOOL, DEPLOY, MODIFY_IAM, etc.
- PolicyRule: Tenant-bounded, versioned, configurable governance rule
- PolicyEvaluationRecord: Shadow decision log with full audit provenance
- ApprovalRecord: Approval tracking state
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EnforcementMode(str, Enum):
    """Graduated autonomy progression states.

    Progression contract:
    OBSERVE -> SHADOW -> APPROVAL_REQUIRED -> ENFORCED -> AUTONOMOUS
    """

    OBSERVE = "OBSERVE"
    SHADOW = "SHADOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ENFORCED = "ENFORCED"
    AUTONOMOUS = "AUTONOMOUS"


class PolicyDecision(str, Enum):
    """Evaluated runtime decision."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class RiskClassification(str, Enum):
    """Risk tier of the requested action."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionType(str, Enum):
    """Standard categorized actions."""

    READ_REPOSITORY = "read_repository"
    CREATE_BRANCH = "create_branch"
    OPEN_PR = "open_pr"
    MERGE_PR = "merge_pr"
    EXECUTE_TOOL = "execute_tool"
    DEPLOY = "deploy"
    CHANGE_IAM = "change_iam"
    INVOKE_LLM = "invoke_llm"
    CUSTOM = "custom"


@dataclass
class PolicyRule:
    """A versioned, tenant-isolated governance rule."""

    policy_id: str
    name: str
    workspace_id: str = "default"
    action_type: str = "*"  # Wildcard or specific ActionType
    risk_level: RiskClassification = RiskClassification.MEDIUM
    decision_if_matched: PolicyDecision = PolicyDecision.REQUIRE_APPROVAL
    condition_expression: str = "true"  # e.g. "budget > 10.0" or "target_branch == 'main'"
    max_cost_usd: float | None = None
    target_pattern: str = "*"
    version: int = 1
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint of policy contents."""
        content = f"{self.policy_id}:{self.workspace_id}:{self.action_type}:{self.condition_expression}:{self.decision_if_matched}:{self.version}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class PolicyEvaluationRecord:
    """Immutable audit record of a shadow or runtime policy evaluation."""

    evaluation_id: str
    workspace_id: str
    agent_id: str
    task_id: str | None
    run_id: str | None
    action_type: str
    target: str
    enforcement_mode: EnforcementMode
    decision: PolicyDecision
    effective_action_taken: str  # e.g. "ALLOWED_BY_SHADOW_OVERRIDE" or "BLOCKED"
    matched_policy_id: str | None
    reason: str
    cost_usd: float = 0.0
    context_metadata: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "action_type": self.action_type,
            "target": self.target,
            "enforcement_mode": self.enforcement_mode.value,
            "decision": self.decision.value,
            "effective_action_taken": self.effective_action_taken,
            "matched_policy_id": self.matched_policy_id,
            "reason": self.reason,
            "cost_usd": self.cost_usd,
            "context_metadata": self.context_metadata,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


@dataclass
class ApprovalRecord:
    """Tracks human review / approval state for actions flagged REQUIRE_APPROVAL."""

    approval_id: str
    evaluation_id: str
    workspace_id: str
    status: str = "pending"  # pending | approved | rejected
    approver: str | None = None
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
