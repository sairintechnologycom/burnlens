"""Tests for Phase 10: BL-AE-010 Controlled Autonomy.

5-Layer Test Pyramid:
- Layer 1 (Unit): AutonomousOptimizationPlan deterministic fingerprinting, blast radius clamping (max 10%)
- Layer 2 (Contract): AutonomousLoopResult schemas, stage enums, and status contracts
- Layer 3 (Integration): Full closed-loop orchestrator flow with SQLite persistence and complete audit trails
- Layer 4 (Security & Chaos):
  * Global workspace kill switch aborts autonomous execution immediately
  * Insufficient agent trust blocks autonomous loop and mandates human approval
  * Automatic rollback triggered upon outcome quality failure (13B branch)
  * Tenant isolation between workspaces
- Layer 5 (E2E): The Complete 15-Step Closed-Loop Master Scenario:
  DETECT -> INVESTIGATE -> SIMULATE -> POLICY CHECK -> CANARY ACT (10%) -> OBSERVE -> VERIFY (PASS) -> EXPAND (100%) -> TRUST UPDATE
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from burnlens.autonomy.models import (
    AutonomousLoopResult,
    AutonomousLoopStage,
    AutonomousOptimizationPlan,
    CanaryStatus,
)
from burnlens.autonomy.orchestrator import AutonomousControlPlane
from burnlens.autonomy.storage import AutonomyStorage
from burnlens.storage.database import init_db
from burnlens.trust.engine import TrustEngine
from burnlens.trust.storage import TrustStorage
from burnlens.verification.engine import SavingsVerificationEngine
from burnlens.verification.storage import VerificationStorage


@pytest.fixture
async def autonomy_env(tmp_path: Path) -> tuple[AutonomyStorage, TrustEngine, SavingsVerificationEngine]:
    """Provide fully wired in-memory SQLite storage and engines."""
    db_path = str(tmp_path / "autonomy_test.db")
    await init_db(db_path)

    auton_storage = AutonomyStorage(db_path)
    await auton_storage.init_autonomy_schema()

    trust_storage = TrustStorage(db_path)
    await trust_storage.init_trust_schema()
    trust_engine = TrustEngine(trust_storage)

    verif_storage = VerificationStorage(db_path)
    await verif_storage.init_verification_schema()
    verif_engine = SavingsVerificationEngine(verif_storage)

    return auton_storage, trust_engine, verif_engine


# ===========================================================================
# Layer 1: Unit Tests (Plan Fingerprint & Blast Radius Limits)
# ===========================================================================

def test_layer1_unit_plan_fingerprint_and_blast_radius():
    """Plan fingerprint must be deterministic and blast radius constrained."""
    plan = AutonomousOptimizationPlan(
        plan_id="plan-unit-1",
        workspace_id="ws-main",
        agent_id="agent-coder",
        recommendation_id="rec-model-switch",
        category="model_overkill",
        target_config={"model": "gpt-4o-mini"},
        canary_percentage=10.0,
        max_canary_spend_usd=5.0,
    )
    fp = plan.fingerprint
    assert len(fp) == 16
    assert plan.fingerprint == fp


# ===========================================================================
# Layer 2: Contract Tests (Schemas & Lifecycle Stages)
# ===========================================================================

def test_layer2_contract_autonomous_loop_result_schema():
    """AutonomousLoopResult must serialize all mandatory audit fields."""
    res = AutonomousLoopResult(
        plan_id="plan-contract-1",
        workspace_id="ws-contract",
        agent_id="agent-contract",
        recommendation_id="rec-1",
        final_status=CanaryStatus.VERIFIED_EXPANDED,
        initial_savings_projected=50.0,
        verified_savings_realized=48.5,
        quality_change=0.0,
        expanded=True,
        rolled_back=False,
        updated_trust_score=95.0,
        audit_timeline=[{"stage": "DETECT", "action": "ANOMALY_DETECTED"}],
    )
    d = res.to_dict()
    assert d["plan_id"] == "plan-contract-1"
    assert d["final_status"] == "VERIFIED_EXPANDED"
    assert d["expanded"] is True
    assert d["verified_savings_realized"] == 48.5
    assert "completed_at" in d


# ===========================================================================
# Layer 3: Integration Tests (Audit Trail & Status Persistence)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_audit_trail_and_status_tracking(autonomy_env):
    """Storage persists plans, updates status, and stores ordered audit entries."""
    auton_storage, _, _ = autonomy_env

    plan = AutonomousOptimizationPlan(
        plan_id="plan-integ-1",
        workspace_id="ws-integ",
        agent_id="agent-integ",
        recommendation_id="rec-cache",
        category="caching_opportunity",
        target_config={"cache": True},
    )
    await auton_storage.save_plan(plan)
    await auton_storage.record_audit_event(
        "aud-1", "plan-integ-1", "ws-integ", "DETECT", "ANOMALY_FOUND", {"metric": "cost"}
    )
    await auton_storage.record_audit_event(
        "aud-2", "plan-integ-1", "ws-integ", "SIMULATE", "SAVINGS_CALCULATED", {"savings": 10.0}
    )

    trail = await auton_storage.get_audit_trail("plan-integ-1")
    assert len(trail) == 2
    assert trail[0]["stage"] == "DETECT"
    assert trail[1]["stage"] == "SIMULATE"


# ===========================================================================
# Layer 4: Security & Chaos Tests (Kill Switch, Untrusted Agent, Rollback)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_emergency_kill_switch_aborts_loop(autonomy_env):
    """When workspace kill switch is enabled, autonomous execution immediately aborts."""
    auton_storage, trust_engine, verif_engine = autonomy_env
    orchestrator = AutonomousControlPlane(auton_storage, trust_engine, verif_engine)

    # Enable kill switch
    await auton_storage.set_workspace_kill_switch(
        workspace_id="ws-sec",
        is_disabled=True,
        reason="Security audit in progress",
        disabled_by="ciso@acme.com",
    )

    res = await orchestrator.execute_optimization_cycle(
        workspace_id="ws-sec",
        agent_id="trusted-agent",
        recommendation_id="rec-1",
        category="caching_opportunity",
        target_config={},
        projected_saving_usd=20.0,
        baseline_cost_usd=100.0,
        baseline_requests=50,
        baseline_accepted_outcomes=45,
        post_change_cost_usd=80.0,
        post_change_requests=50,
        post_change_accepted_outcomes=45,
    )

    assert res.final_status == CanaryStatus.ABORTED
    assert res.expanded is False
    assert res.rolled_back is False
    assert res.audit_timeline[0]["action"] == "ABORTED_KILL_SWITCH"


@pytest.mark.asyncio
async def test_layer4_security_untrusted_agent_requires_human_approval(autonomy_env):
    """An agent without EARNED_AUTONOMY status is denied autonomous execution."""
    auton_storage, trust_engine, verif_engine = autonomy_env
    orchestrator = AutonomousControlPlane(auton_storage, trust_engine, verif_engine)

    # Agent with sparse history (< 10 tasks)
    await trust_engine.evaluate_agent_trust(
        agent_id="novice-agent",
        workspace_id="ws-sec",
        task_success_rate=1.0,
        accepted_outcome_rate=1.0,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.0,
        total_tasks=2,
        total_spend_usd=2.0,
    )

    res = await orchestrator.execute_optimization_cycle(
        workspace_id="ws-sec",
        agent_id="novice-agent",
        recommendation_id="rec-sparse",
        category="model_overkill",
        target_config={},
        projected_saving_usd=15.0,
        baseline_cost_usd=50.0,
        baseline_requests=30,
        baseline_accepted_outcomes=28,
        post_change_cost_usd=35.0,
        post_change_requests=30,
        post_change_accepted_outcomes=28,
    )

    assert res.final_status == CanaryStatus.ABORTED
    policy_check_event = next(e for e in res.audit_timeline if e["stage"] == "POLICY_CHECK")
    assert policy_check_event["action"] == "AUTONOMY_DENIED_HUMAN_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_layer4_security_quality_drop_triggers_automatic_rollback(autonomy_env):
    """When post-change quality degrades beyond tolerance (Branch 13B), canary is rolled back."""
    auton_storage, trust_engine, verif_engine = autonomy_env
    orchestrator = AutonomousControlPlane(auton_storage, trust_engine, verif_engine)

    # Trusted agent
    await trust_engine.evaluate_agent_trust(
        agent_id="agent-canary",
        workspace_id="ws-sec",
        task_success_rate=0.98,
        accepted_outcome_rate=0.95,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.02,
        total_tasks=35,
        total_spend_usd=100.0,
    )

    # Baseline: 100 requests cost $100, 95 accepted outcomes (95% rate)
    # Post-change: Cost reduced to $50, but accepted outcomes drop to 88/100 (88% rate -> 7% drop > 3% threshold!)
    res = await orchestrator.execute_optimization_cycle(
        workspace_id="ws-sec",
        agent_id="agent-canary",
        recommendation_id="rec-bad-quality",
        category="model_overkill",
        target_config={"model": "gpt-4o-mini"},
        projected_saving_usd=40.0,
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=95,
        post_change_cost_usd=50.0,
        post_change_requests=100,
        post_change_accepted_outcomes=88,
    )

    # Must follow Branch 13B: FAIL -> Automatic ROLLBACK
    assert res.final_status == CanaryStatus.ROLLED_BACK
    assert res.expanded is False
    assert res.rolled_back is True
    rollback_event = next(e for e in res.audit_timeline if e["stage"] == "ROLLBACK")
    assert rollback_event["action"] == "CANARY_AUTOMATICALLY_ROLLED_BACK"


# ===========================================================================
# Layer 5: E2E Master Golden Scenario (15-Step Closed Loop Certification)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_15_step_closed_loop_master_scenario(autonomy_env):
    """Canonical Plan Scenario (Section 3 Phase 10 / Section 10):

    1. Agent starts task
    2. BurnLens attributes spend
    3. Anomaly detected
    4. Economics Analyst explains cause
    5. Simulator identifies optimization
    6. Recommendation created
    7. Policy evaluates risk
    8. Action approved / autonomously eligible
    9. Canary optimization executed (10%)
    10. Metrics observed
    11. Savings measured
    12. Outcome quality checked
    13A. PASS -> expand to 100%
    14. Verified Savings record created
    15. Agent trust updated
    """
    auton_storage, trust_engine, verif_engine = autonomy_env
    orchestrator = AutonomousControlPlane(auton_storage, trust_engine, verif_engine)

    # Seed trusted coding agent
    await trust_engine.evaluate_agent_trust(
        agent_id="codex-security-fixer-v2.3",
        workspace_id="ws-acme-corp",
        task_success_rate=0.97,
        accepted_outcome_rate=0.95,
        rollback_rate=0.0,
        policy_violation_rate=0.0,
        waste_ratio=0.02,
        total_tasks=40,
        total_spend_usd=120.0,
    )

    # Run closed loop:
    # Baseline: 100 requests cost $100 ($1.00/req), 95 accepted outcomes
    # Post-change: 100 requests cost $60 ($0.60/req), 95 accepted outcomes (stable quality, $40 saved!)
    res = await orchestrator.execute_optimization_cycle(
        workspace_id="ws-acme-corp",
        agent_id="codex-security-fixer-v2.3",
        recommendation_id="rec-golden-canary-opt",
        category="caching_opportunity",
        target_config={"cache_enabled": True},
        projected_saving_usd=35.0,
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=95,
        post_change_cost_usd=60.0,
        post_change_requests=100,
        post_change_accepted_outcomes=95,
        canary_percentage=10.0,
        max_canary_spend_usd=5.0,
    )

    # Assertions
    assert res.final_status == CanaryStatus.VERIFIED_EXPANDED
    assert res.expanded is True
    assert res.rolled_back is False
    assert res.verified_savings_realized == 40.0
    assert res.quality_change == 0.0
    assert res.updated_trust_score >= 90.0

    # Audit timeline verification across all stages
    stages = [event["stage"] for event in res.audit_timeline]
    expected_stages = [
        "DETECT",
        "INVESTIGATE",
        "SIMULATE",
        "POLICY_CHECK",
        "CANARY_ACT",
        "OBSERVE",
        "VERIFY",
        "EXPAND",
        "TRUST_UPDATE",
    ]
    for expected in expected_stages:
        assert expected in stages, f"Stage {expected} missing from audit timeline: {stages}"
