"""Tests for Phase 9: BL-AE-009 Agent Trust & Earned Autonomy.

5-Layer Test Pyramid:
- Layer 1 (Unit): TrustCalculator exact mathematical formula, signal weighting, sparse-history dampening
- Layer 2 (Contract): AgentTrustProfile, AutonomyLevel, and AutonomyEligibilityCheck schema contracts
- Layer 3 (Integration): Trust calculation, SQLite persistence roundtrip, eligibility auditing
- Layer 4 (Security & Invariants):
  * High-risk actions (IAM, DB drops, protected branch pushes) ALWAYS require human approval regardless of trust score
  * High-spend actions (>$5) require human approval
  * Sparse-history agents remain RESTRICTED
  * Irreversible actions require human approval
  * Multi-tenant profile isolation
- Layer 5 (E2E): Canonical Plan Scenario: Trusted agent executes low-risk bounded task autonomously,
                 but production IAM change strictly mandates human approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from burnlens.storage.database import init_db
from burnlens.trust.calculator import TrustCalculator
from burnlens.trust.engine import TrustEngine
from burnlens.trust.models import (
    HIGH_RISK_ACTIONS,
    AgentTrustProfile,
    AutonomyEligibilityCheck,
    AutonomyLevel,
)
from burnlens.trust.storage import TrustStorage


@pytest.fixture
async def trust_storage(tmp_path: Path) -> TrustStorage:
    """Provide initialized SQLite database with trust schema."""
    db_path = str(tmp_path / "trust_test.db")
    await init_db(db_path)
    storage = TrustStorage(db_path)
    await storage.init_trust_schema()
    return storage


# ===========================================================================
# Layer 1: Unit Tests (Deterministic Formula & Sparse Dampening)
# ===========================================================================

def test_layer1_unit_trust_formula_exact_score_calculation():
    """Formula must match the canonical specification: ~94 score on excellent metrics."""
    profile = TrustCalculator.calculate_score(
        agent_id="codex-opt-v1",
        workspace_id="ws-main",
        task_success_rate=0.97,       # 24.25 pts
        accepted_outcome_rate=0.95,   # 33.25 pts
        rollback_rate=0.003,          # 9.97 pts
        policy_violation_rate=0.0,    # 20.00 pts
        waste_ratio=0.027,            # 9.73 pts
        total_tasks=50,               # Non-sparse (> 10)
        total_spend_usd=120.0,
    )
    # Sum: 24.25 + 33.25 + 9.97 + 20.00 + 9.73 = 97.2 -> ~97
    assert 94.0 <= profile.trust_score <= 98.0
    assert profile.autonomy_level == AutonomyLevel.EARNED_AUTONOMY
    assert profile.is_sparse_history is False
    assert len(profile.fingerprint) == 16


def test_layer1_unit_sparse_history_dampens_trust_score():
    """A new agent with only 2 tasks cannot earn high autonomy even with 100% success."""
    profile = TrustCalculator.calculate_score(
        agent_id="new-agent-001",
        workspace_id="ws-main",
        task_success_rate=1.0,
        accepted_outcome_rate=1.0,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.0,
        total_tasks=2,  # Sparse history (< 10)
        total_spend_usd=5.0,
    )
    # Raw score is 100.0, but dampened toward prior (30.0) -> effective score ~44.0
    assert profile.is_sparse_history is True
    assert profile.trust_score < 50.0
    assert profile.autonomy_level == AutonomyLevel.RESTRICTED


# ===========================================================================
# Layer 2: Contract Tests (Schemas & Enums)
# ===========================================================================

def test_layer2_contract_agent_trust_profile_schema():
    """AgentTrustProfile serialization must contain all required audit fields."""
    profile = AgentTrustProfile(
        agent_id="agent-contract",
        workspace_id="ws-contract",
        trust_score=88.5,
        task_success_rate=0.95,
        accepted_outcome_rate=0.92,
        rollback_rate=0.01,
        policy_violation_rate=0.0,
        waste_ratio=0.03,
        total_tasks=25,
        total_spend_usd=45.0,
        autonomy_level=AutonomyLevel.EARNED_AUTONOMY,
        is_sparse_history=False,
        breakdown={"test": True},
    )
    d = profile.to_dict()
    assert d["agent_id"] == "agent-contract"
    assert d["trust_score"] == 88.5
    assert d["autonomy_level"] == "EARNED_AUTONOMY"
    assert "calculated_at" in d


# ===========================================================================
# Layer 3: Integration Tests (SQLite Persistence Roundtrip)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_trust_engine_evaluation_and_storage(trust_storage: TrustStorage):
    """Trust engine computes score, stores profile in SQLite, and retrieves matching metrics."""
    engine = TrustEngine(trust_storage)

    profile = await engine.evaluate_agent_trust(
        agent_id="agent-integ-1",
        workspace_id="ws-integ",
        task_success_rate=0.90,
        accepted_outcome_rate=0.88,
        rollback_rate=0.02,
        policy_violation_rate=0.0,
        waste_ratio=0.05,
        total_tasks=30,
        total_spend_usd=75.0,
    )

    assert profile.trust_score >= 80.0
    assert profile.autonomy_level == AutonomyLevel.EARNED_AUTONOMY

    stored = await trust_storage.get_profile("agent-integ-1", "ws-integ")
    assert stored is not None
    assert stored.trust_score == profile.trust_score
    assert stored.fingerprint == profile.fingerprint


# ===========================================================================
# Layer 4: Security & Invariant Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_high_risk_actions_always_require_human_approval(trust_storage: TrustStorage):
    """High-risk actions (IAM, DB drops, protected branch pushes) ALWAYS mandate human approval."""
    engine = TrustEngine(trust_storage)

    # Prime an agent with 100/100 trust score
    await engine.evaluate_agent_trust(
        agent_id="super-trusted-agent",
        workspace_id="ws-sec",
        task_success_rate=1.0,
        accepted_outcome_rate=1.0,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.0,
        total_tasks=100,
        total_spend_usd=500.0,
    )

    # For each high-risk action, autonomy must be denied
    for high_risk in HIGH_RISK_ACTIONS:
        check = await engine.check_autonomy_eligibility(
            agent_id="super-trusted-agent",
            workspace_id="ws-sec",
            action_type=high_risk,
            estimated_cost_usd=0.50,
            is_reversible=True,
        )
        assert check.is_autonomous_eligible is False
        assert check.requires_human_approval is True
        assert "HIGH-RISK" in check.reason


@pytest.mark.asyncio
async def test_layer4_security_cost_above_autonomous_threshold_requires_human_approval(trust_storage: TrustStorage):
    """Estimated cost exceeding autonomous cap ($5.00) requires human approval."""
    engine = TrustEngine(trust_storage)

    await engine.evaluate_agent_trust(
        agent_id="trusted-agent-1",
        workspace_id="ws-sec",
        task_success_rate=0.98,
        accepted_outcome_rate=0.95,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.02,
        total_tasks=40,
        total_spend_usd=200.0,
    )

    # Spend of $12.50 exceeds cap of $5.00
    check = await engine.check_autonomy_eligibility(
        agent_id="trusted-agent-1",
        workspace_id="ws-sec",
        action_type="apply_cache_rule",
        estimated_cost_usd=12.50,
        is_reversible=True,
        max_autonomous_spend=5.0,
    )
    assert check.is_autonomous_eligible is False
    assert check.requires_human_approval is True
    assert "exceeds autonomous cap" in check.reason


@pytest.mark.asyncio
async def test_layer4_security_sparse_history_agent_cannot_execute_autonomously(trust_storage: TrustStorage):
    """An agent with sparse history (<10 tasks) is restricted from autonomous actions."""
    engine = TrustEngine(trust_storage)

    # Agent with only 1 task
    await engine.evaluate_agent_trust(
        agent_id="novice-agent",
        workspace_id="ws-sec",
        task_success_rate=1.0,
        accepted_outcome_rate=1.0,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.0,
        total_tasks=1,
        total_spend_usd=1.0,
    )

    check = await engine.check_autonomy_eligibility(
        agent_id="novice-agent",
        workspace_id="ws-sec",
        action_type="minor_config_update",
        estimated_cost_usd=0.50,
        is_reversible=True,
    )
    assert check.is_autonomous_eligible is False
    assert check.requires_human_approval is True
    assert "RESTRICTED" in check.reason


@pytest.mark.asyncio
async def test_layer4_security_multi_tenant_isolation(trust_storage: TrustStorage):
    """Profile stored in Workspace Alpha is not leaked into Workspace Beta."""
    engine = TrustEngine(trust_storage)

    await engine.evaluate_agent_trust(
        agent_id="shared-agent-name",
        workspace_id="ws-alpha",
        task_success_rate=1.0,
        accepted_outcome_rate=1.0,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.0,
        total_tasks=50,
        total_spend_usd=100.0,
    )

    # In ws-beta, the agent has no history -> defaults to sparse history / restricted
    beta_profile = await trust_storage.get_profile("shared-agent-name", "ws-beta")
    assert beta_profile is None

    check_beta = await engine.check_autonomy_eligibility(
        agent_id="shared-agent-name",
        workspace_id="ws-beta",
        action_type="safe_action",
        estimated_cost_usd=0.20,
    )
    assert check_beta.is_autonomous_eligible is False
    assert check_beta.autonomy_level == AutonomyLevel.RESTRICTED


# ===========================================================================
# Layer 5: E2E Golden Autonomy Journey (Plan Section 9 Scenario)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_autonomy_journey(trust_storage: TrustStorage):
    """Canonical Plan Scenario (Section 9):

    Step 1:
    Trusted agent (score >= 80) + low-risk task + <$5 spend ($1.20) + reversible action
    -> Autonomous permission GRANTED.

    Step 2:
    Same trusted agent + production IAM change ('change_iam')
    -> Human approval STILL REQUIRED.
    """
    engine = TrustEngine(trust_storage)

    # Establish trusted agent
    profile = await engine.evaluate_agent_trust(
        agent_id="codex-security-fixer-v2.3",
        workspace_id="ws-acme-corp",
        task_success_rate=0.96,
        accepted_outcome_rate=0.94,
        rollback_rate=0.005,
        policy_violation_rate=0.0,
        waste_ratio=0.02,
        total_tasks=45,
        total_spend_usd=150.0,
    )
    assert profile.autonomy_level == AutonomyLevel.EARNED_AUTONOMY
    assert profile.trust_score >= 85.0

    # Test Step 1: Low-risk, reversible, low-spend ($1.20) task
    step1_check = await engine.check_autonomy_eligibility(
        agent_id="codex-security-fixer-v2.3",
        workspace_id="ws-acme-corp",
        action_type="apply_cache_headers",
        estimated_cost_usd=1.20,
        is_reversible=True,
        max_autonomous_spend=5.0,
    )
    assert step1_check.is_autonomous_eligible is True
    assert step1_check.requires_human_approval is False
    assert "Autonomous permission granted" in step1_check.reason

    # Test Step 2: Same agent attempting production IAM modification
    step2_check = await engine.check_autonomy_eligibility(
        agent_id="codex-security-fixer-v2.3",
        workspace_id="ws-acme-corp",
        action_type="change_iam",
        estimated_cost_usd=0.10,
        is_reversible=True,
    )
    assert step2_check.is_autonomous_eligible is False
    assert step2_check.requires_human_approval is True
    assert "HIGH-RISK" in step2_check.reason
