"""Phase 9: BL-AE-009 Deterministic Agent Trust Calculator.

Computes explainable, deterministic trust scores (0-100) from historical evidence.
Guarantees:
- Zero opaque LLM evaluation
- Sparse-history Bayesian dampening
- Multi-dimensional signal weighting
- Hard bounds on autonomy tiers
"""
from __future__ import annotations

import logging
from typing import Any

from burnlens.trust.models import AgentTrustProfile, AutonomyLevel

logger = logging.getLogger(__name__)

# Minimum tasks required to exit sparse-history damping
MINIMUM_TASK_HISTORY_THRESHOLD = 10
SPARSE_HISTORY_PRIOR_SCORE = 30.0


class TrustCalculator:
    """Deterministic mathematical scoring engine for agent trustworthiness."""

    @staticmethod
    def calculate_score(
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
        """Compute exact, auditable trust score and autonomy level."""
        # Clamp inputs to valid [0.0, 1.0] ranges
        s_rate = max(0.0, min(1.0, task_success_rate))
        a_rate = max(0.0, min(1.0, accepted_outcome_rate))
        r_rate = max(0.0, min(1.0, rollback_rate))
        v_rate = max(0.0, min(1.0, policy_violation_rate))
        w_ratio = max(0.0, min(1.0, waste_ratio))

        # Weight components (sum = 100.0)
        c_outcome = a_rate * 35.0
        c_success = s_rate * 25.0
        c_violation = (1.0 - v_rate) * 20.0
        c_rollback = (1.0 - r_rate) * 10.0
        c_waste = (1.0 - w_ratio) * 10.0

        raw_score = c_outcome + c_success + c_violation + c_rollback + c_waste
        raw_score = max(0.0, min(100.0, raw_score))

        # Sparse history dampening
        is_sparse = total_tasks < MINIMUM_TASK_HISTORY_THRESHOLD
        if is_sparse:
            # Linear Bayesian interpolation toward prior (30.0)
            confidence_factor = float(total_tasks) / float(MINIMUM_TASK_HISTORY_THRESHOLD)
            effective_score = round(
                (SPARSE_HISTORY_PRIOR_SCORE * (1.0 - confidence_factor)) + (raw_score * confidence_factor),
                1,
            )
        else:
            effective_score = round(raw_score, 1)

        # Autonomy Level determination
        if is_sparse or effective_score < 50.0:
            autonomy_level = AutonomyLevel.RESTRICTED
        elif effective_score < 80.0:
            autonomy_level = AutonomyLevel.STANDARD
        else:
            autonomy_level = AutonomyLevel.EARNED_AUTONOMY

        breakdown: dict[str, Any] = {
            "components": {
                "accepted_outcome_points": round(c_outcome, 2),
                "task_success_points": round(c_success, 2),
                "policy_compliance_points": round(c_violation, 2),
                "rollback_resistance_points": round(c_rollback, 2),
                "efficiency_points": round(c_waste, 2),
            },
            "raw_score": round(raw_score, 1),
            "effective_score": effective_score,
            "sparse_dampened": is_sparse,
            "minimum_history_required": MINIMUM_TASK_HISTORY_THRESHOLD,
        }

        return AgentTrustProfile(
            agent_id=agent_id,
            workspace_id=workspace_id,
            trust_score=effective_score,
            task_success_rate=round(s_rate, 4),
            accepted_outcome_rate=round(a_rate, 4),
            rollback_rate=round(r_rate, 4),
            policy_violation_rate=round(v_rate, 4),
            waste_ratio=round(w_ratio, 4),
            total_tasks=total_tasks,
            total_spend_usd=round(total_spend_usd, 4),
            autonomy_level=autonomy_level,
            is_sparse_history=is_sparse,
            breakdown=breakdown,
        )
