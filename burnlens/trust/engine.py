"""Phase 9: BL-AE-009 Agent Trust & Earned Autonomy Engine.

Coordinates:
- Multi-signal deterministic trust score evaluation
- Action-level earned autonomy eligibility evaluation
- Invariant enforcement: High-risk actions (IAM, DB drops, protected branch pushes)
  ALWAYS require human approval regardless of agent trust score.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from burnlens.trust.calculator import TrustCalculator
from burnlens.trust.models import (
    HIGH_RISK_ACTIONS,
    AgentTrustProfile,
    AutonomyEligibilityCheck,
    AutonomyLevel,
)
from burnlens.trust.storage import TrustStorage

logger = logging.getLogger(__name__)


class TrustEngine:
    """Evaluates agent trust and enforces bounded earned autonomy per action."""

    def __init__(self, storage: TrustStorage) -> None:
        self.storage = storage

    async def evaluate_agent_trust(
        self,
        agent_id: str,
        workspace_id: str,
        task_success_rate: float,
        accepted_outcome_rate: float,
        rollback_rate: float,
        policy_violation_rate: float,
        waste_ratio: float,
        total_tasks: int,
        total_spend_usd: float,
    ) -> AgentTrustProfile:
        """Compute deterministic trust profile from empirical evidence and persist it."""
        profile = TrustCalculator.calculate_score(
            agent_id=agent_id,
            workspace_id=workspace_id,
            task_success_rate=task_success_rate,
            accepted_outcome_rate=accepted_outcome_rate,
            rollback_rate=rollback_rate,
            policy_violation_rate=policy_violation_rate,
            waste_ratio=waste_ratio,
            total_tasks=total_tasks,
            total_spend_usd=total_spend_usd,
        )
        await self.storage.save_profile(profile)
        return profile

    async def check_autonomy_eligibility(
        self,
        agent_id: str,
        workspace_id: str,
        action_type: str,
        estimated_cost_usd: float,
        is_reversible: bool = True,
        max_autonomous_spend: float = 5.0,
    ) -> AutonomyEligibilityCheck:
        """Evaluate if an action is eligible for autonomous execution.

        Core Invariant:
        Autonomy is earned from evidence rather than granted globally.
        High-risk actions (IAM, protected branches, database drops) NEVER execute
        autonomously, regardless of trust score.
        """
        now = datetime.now(timezone.utc)
        profile = await self.storage.get_profile(agent_id, workspace_id)

        # If agent profile doesn't exist yet, evaluate default baseline (sparse history)
        if profile is None:
            profile = await self.evaluate_agent_trust(
                agent_id=agent_id,
                workspace_id=workspace_id,
                task_success_rate=0.0,
                accepted_outcome_rate=0.0,
                rollback_rate=0.0,
                policy_violation_rate=0.0,
                waste_ratio=0.0,
                total_tasks=0,
                total_spend_usd=0.0,
            )

        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        action_clean = action_type.strip().lower()

        # Invariant 1: High-risk actions ALWAYS require human approval
        if action_clean in HIGH_RISK_ACTIONS:
            check = AutonomyEligibilityCheck(
                agent_id=agent_id,
                workspace_id=workspace_id,
                action_type=action_type,
                estimated_cost_usd=estimated_cost_usd,
                is_autonomous_eligible=False,
                requires_human_approval=True,
                trust_score=profile.trust_score,
                autonomy_level=profile.autonomy_level,
                reason=f"Action '{action_type}' is classified as HIGH-RISK. Mandatory human approval required.",
                evaluated_at=now,
            )
            await self.storage.record_eligibility_audit(audit_id, check)
            return check

        # Invariant 2: Irreversible actions require human approval
        if not is_reversible:
            check = AutonomyEligibilityCheck(
                agent_id=agent_id,
                workspace_id=workspace_id,
                action_type=action_type,
                estimated_cost_usd=estimated_cost_usd,
                is_autonomous_eligible=False,
                requires_human_approval=True,
                trust_score=profile.trust_score,
                autonomy_level=profile.autonomy_level,
                reason="Irreversible action requires human approval.",
                evaluated_at=now,
            )
            await self.storage.record_eligibility_audit(audit_id, check)
            return check

        # Invariant 3: Cost must be bounded by autonomous threshold ($5 default)
        if estimated_cost_usd > max_autonomous_spend:
            check = AutonomyEligibilityCheck(
                agent_id=agent_id,
                workspace_id=workspace_id,
                action_type=action_type,
                estimated_cost_usd=estimated_cost_usd,
                is_autonomous_eligible=False,
                requires_human_approval=True,
                trust_score=profile.trust_score,
                autonomy_level=profile.autonomy_level,
                reason=f"Estimated cost ${estimated_cost_usd:.2f} exceeds autonomous cap of ${max_autonomous_spend:.2f}.",
                evaluated_at=now,
            )
            await self.storage.record_eligibility_audit(audit_id, check)
            return check

        # Invariant 4: Agent must possess EARNED_AUTONOMY tier (score >= 80.0, non-sparse history)
        if profile.autonomy_level != AutonomyLevel.EARNED_AUTONOMY:
            check = AutonomyEligibilityCheck(
                agent_id=agent_id,
                workspace_id=workspace_id,
                action_type=action_type,
                estimated_cost_usd=estimated_cost_usd,
                is_autonomous_eligible=False,
                requires_human_approval=True,
                trust_score=profile.trust_score,
                autonomy_level=profile.autonomy_level,
                reason=(
                    f"Agent autonomy level is '{profile.autonomy_level.value}' (trust score: {profile.trust_score:.1f}). "
                    f"EARNED_AUTONOMY tier (>= 80.0) is required for autonomous execution."
                ),
                evaluated_at=now,
            )
            await self.storage.record_eligibility_audit(audit_id, check)
            return check

        # Invariant 5: Authorized
        check = AutonomyEligibilityCheck(
            agent_id=agent_id,
            workspace_id=workspace_id,
            action_type=action_type,
            estimated_cost_usd=estimated_cost_usd,
            is_autonomous_eligible=True,
            requires_human_approval=False,
            trust_score=profile.trust_score,
            autonomy_level=profile.autonomy_level,
            reason=(
                f"Autonomous permission granted: Trusted agent (score: {profile.trust_score:.1f}), "
                f"low-risk reversible action, cost (${estimated_cost_usd:.2f}) within threshold."
            ),
            evaluated_at=now,
        )
        await self.storage.record_eligibility_audit(audit_id, check)
        return check
