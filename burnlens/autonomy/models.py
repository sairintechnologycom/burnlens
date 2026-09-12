"""Phase 10: BL-AE-010 Controlled Autonomy Data Models.

Defines:
- CanaryStatus: PROPOSED, CANARY_ACTIVE, VERIFIED_EXPANDED, ROLLED_BACK, ABORTED
- AutonomousLoopStage: Complete 15-step closed-loop lifecycle stages
- AutonomousOptimizationPlan: Bounded, reversible canary optimization configuration
- AutonomousLoopResult: Comprehensive outcome record with verified savings and trust adjustment
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CanaryStatus(str, Enum):
    """Lifecycle state of an autonomous canary optimization."""

    PROPOSED = "PROPOSED"
    CANARY_ACTIVE = "CANARY_ACTIVE"
    VERIFIED_EXPANDED = "VERIFIED_EXPANDED"
    ROLLED_BACK = "ROLLED_BACK"
    ABORTED = "ABORTED"


class AutonomousLoopStage(str, Enum):
    """Stages of the closed-loop economic optimization cycle."""

    DETECT = "DETECT"
    INVESTIGATE = "INVESTIGATE"
    SIMULATE = "SIMULATE"
    POLICY_CHECK = "POLICY_CHECK"
    CANARY_ACT = "CANARY_ACT"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"
    EXPAND = "EXPAND"
    ROLLBACK = "ROLLBACK"
    TRUST_UPDATE = "TRUST_UPDATE"


@dataclass
class AutonomousOptimizationPlan:
    """Bounded, reversible autonomous optimization plan."""

    plan_id: str
    workspace_id: str
    agent_id: str
    recommendation_id: str
    category: str
    target_config: dict[str, Any]
    canary_percentage: float = 10.0          # Max 10% blast radius
    max_canary_spend_usd: float = 5.0        # Max spend cap
    canary_status: CanaryStatus = CanaryStatus.PROPOSED
    is_kill_switched: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint of plan configuration."""
        raw = (
            f"{self.plan_id}:{self.workspace_id}:{self.agent_id}:{self.recommendation_id}:"
            f"{self.category}:{self.canary_percentage}:{self.max_canary_spend_usd}:"
            f"{self.canary_status.value}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class AutonomousLoopResult:
    """Outcome of a complete closed-loop autonomous optimization cycle."""

    plan_id: str
    workspace_id: str
    agent_id: str
    recommendation_id: str
    final_status: CanaryStatus
    initial_savings_projected: float
    verified_savings_realized: float
    quality_change: float
    expanded: bool
    rolled_back: bool
    updated_trust_score: float
    audit_timeline: list[dict[str, Any]] = field(default_factory=list)
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "recommendation_id": self.recommendation_id,
            "final_status": self.final_status.value,
            "initial_savings_projected": self.initial_savings_projected,
            "verified_savings_realized": self.verified_savings_realized,
            "quality_change": self.quality_change,
            "expanded": self.expanded,
            "rolled_back": self.rolled_back,
            "updated_trust_score": self.updated_trust_score,
            "audit_timeline": self.audit_timeline,
            "completed_at": self.completed_at.isoformat(),
        }
