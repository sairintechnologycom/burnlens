"""Tests for Phase 5: BL-AE-005 Governance Foundation (Shadow Mode).

5-Layer Test Pyramid:
- Layer 1 (Unit): PolicyRule versioning, fingerprinting, and rule evaluation logic
- Layer 2 (Contract): EvaluationRecord schemas, state transitions, and EnforcementMode validation
- Layer 3 (Integration): Shadow evaluation against representative multi-action workload
- Layer 4 (Security): Tenant isolation of policy rules and immutable audit log protection
- Layer 5 (E2E): Coding agent scenario: Merge PR evaluated to REQUIRE_APPROVAL, but permitted under SHADOW mode
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from burnlens.governance.engine import GovernanceEngine, PolicyStorage
from burnlens.governance.models import (
    ActionType,
    EnforcementMode,
    PolicyDecision,
    PolicyEvaluationRecord,
    PolicyRule,
    RiskClassification,
)
from burnlens.storage.database import init_db


@pytest.fixture
async def gov_db(tmp_path: Path) -> str:
    """Provide initialized SQLite database with governance schema."""
    db_path = str(tmp_path / "governance_test.db")
    await init_db(db_path)
    storage = PolicyStorage(db_path)
    await storage.init_governance_schema()
    return db_path


# ===========================================================================
# Layer 1: Unit Tests (Policy Rule Versioning & Evaluation Logic)
# ===========================================================================

def test_layer1_unit_policy_rule_fingerprint():
    """Policy fingerprint must be deterministic based on content and version."""
    rule1 = PolicyRule(
        policy_id="pol-1",
        name="Block IAM",
        workspace_id="ws-1",
        action_type="change_iam",
        risk_level=RiskClassification.CRITICAL,
        decision_if_matched=PolicyDecision.DENY,
        condition_expression="true",
        version=1,
    )
    rule2 = PolicyRule(
        policy_id="pol-1",
        name="Block IAM Modified",
        workspace_id="ws-1",
        action_type="change_iam",
        risk_level=RiskClassification.CRITICAL,
        decision_if_matched=PolicyDecision.DENY,
        condition_expression="true",
        version=1,
    )
    # Identical semantic content -> same fingerprint
    assert rule1.fingerprint == rule2.fingerprint

    # Version bump -> distinct fingerprint
    rule3 = PolicyRule(
        policy_id="pol-1",
        name="Block IAM",
        workspace_id="ws-1",
        action_type="change_iam",
        risk_level=RiskClassification.CRITICAL,
        decision_if_matched=PolicyDecision.DENY,
        condition_expression="true",
        version=2,
    )
    assert rule1.fingerprint != rule3.fingerprint


@pytest.mark.asyncio
async def test_layer1_unit_policy_version_bumping(gov_db: str):
    """Saving updated policy rule must increment version automatically."""
    storage = PolicyStorage(gov_db)
    rule = PolicyRule(
        policy_id="pol-custom-1",
        name="Initial Rule",
        workspace_id="ws-100",
        action_type="deploy",
        decision_if_matched=PolicyDecision.REQUIRE_APPROVAL,
        version=1,
    )
    await storage.save_policy_rule(rule)

    rules = await storage.get_active_rules("ws-100")
    custom = next(r for r in rules if r.policy_id == "pol-custom-1")
    assert custom.version == 1

    # Update rule
    rule_v2 = PolicyRule(
        policy_id="pol-custom-1",
        name="Updated Rule",
        workspace_id="ws-100",
        action_type="deploy",
        decision_if_matched=PolicyDecision.DENY,
        version=1,
    )
    await storage.save_policy_rule(rule_v2)

    rules_updated = await storage.get_active_rules("ws-100")
    custom_updated = next(r for r in rules_updated if r.policy_id == "pol-custom-1")
    assert custom_updated.version == 2
    assert custom_updated.decision_if_matched == PolicyDecision.DENY


# ===========================================================================
# Layer 2: Contract Tests (Enforcement Modes & Audit Record Schemas)
# ===========================================================================

def test_layer2_contract_enforcement_mode_progression():
    """Verify non-negotiable progression states."""
    expected_modes = ["OBSERVE", "SHADOW", "APPROVAL_REQUIRED", "ENFORCED", "AUTONOMOUS"]
    actual_modes = [m.value for m in EnforcementMode]
    assert actual_modes == expected_modes


def test_layer2_contract_evaluation_record_schema():
    """PolicyEvaluationRecord serialization must contain required audit fields."""
    rec = PolicyEvaluationRecord(
        evaluation_id="eval-123",
        workspace_id="ws-prod",
        agent_id="agent-coder",
        task_id="task-1",
        run_id="run-1",
        action_type="merge_pr",
        target="repo:main",
        enforcement_mode=EnforcementMode.SHADOW,
        decision=PolicyDecision.REQUIRE_APPROVAL,
        effective_action_taken="ALLOWED_BY_SHADOW_MODE",
        matched_policy_id="pol-default-merge-pr",
        reason="Protected branch merge",
        cost_usd=1.25,
        context_metadata={"target_branch": "main"},
    )
    d = rec.to_dict()
    assert d["evaluation_id"] == "eval-123"
    assert d["enforcement_mode"] == "SHADOW"
    assert d["decision"] == "REQUIRE_APPROVAL"
    assert d["effective_action_taken"] == "ALLOWED_BY_SHADOW_MODE"
    assert d["cost_usd"] == 1.25


# ===========================================================================
# Layer 3: Integration Tests (Shadow Evaluation of Representative Workload)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_shadow_workload_evaluation(gov_db: str):
    """Simulate a realistic batch of 100 mixed agent actions in SHADOW mode:
    - 60 repo reads -> Would ALLOW
    - 25 branch creates -> Would ALLOW
    - 10 PR merges to main -> Would REQUIRE_APPROVAL
    - 5 IAM modifications -> Would DENY
    Verify that 100% of actions are allowed under shadow mode while predictions match.
    """
    engine = GovernanceEngine(gov_db, mode=EnforcementMode.SHADOW)
    ws = "ws-workload"

    # 1. 60 reads
    for i in range(60):
        res = await engine.evaluate_action(
            workspace_id=ws,
            agent_id="agent-coder",
            action_type=ActionType.READ_REPOSITORY.value,
            target="repo/src/code.py",
        )
        assert res.decision == PolicyDecision.ALLOW
        assert res.effective_action_taken == "ALLOWED_BY_SHADOW_MODE"

    # 2. 25 branch creates
    for i in range(25):
        res = await engine.evaluate_action(
            workspace_id=ws,
            agent_id="agent-coder",
            action_type=ActionType.CREATE_BRANCH.value,
            target="feat/bl-ae-005",
        )
        assert res.decision == PolicyDecision.ALLOW
        assert res.effective_action_taken == "ALLOWED_BY_SHADOW_MODE"

    # 3. 10 PR merges to main
    for i in range(10):
        res = await engine.evaluate_action(
            workspace_id=ws,
            agent_id="agent-coder",
            action_type=ActionType.MERGE_PR.value,
            target="repo/pull/1",
            context_metadata={"target_branch": "main"},
        )
        assert res.decision == PolicyDecision.REQUIRE_APPROVAL
        assert res.effective_action_taken == "ALLOWED_BY_SHADOW_MODE"

    # 4. 5 IAM changes
    for i in range(5):
        res = await engine.evaluate_action(
            workspace_id=ws,
            agent_id="agent-coder",
            action_type=ActionType.CHANGE_IAM.value,
            target="aws:iam:role/AdminRole",
        )
        assert res.decision == PolicyDecision.DENY
        assert res.effective_action_taken == "ALLOWED_BY_SHADOW_MODE"

    # Verify aggregated summary
    summary = await engine.get_shadow_evaluation_summary(ws)
    assert summary["total_evaluations"] == 100
    assert summary["would_allow"] == 85
    assert summary["would_require_approval"] == 10
    assert summary["would_deny"] == 5


# ===========================================================================
# Layer 4: Security Tests (Tenant Isolation of Policy Rules)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_tenant_isolation_of_policies(gov_db: str):
    """Custom policy created in workspace A must not be visible or evaluated in workspace B."""
    storage = PolicyStorage(gov_db)

    # Specific rule in ws-tenant-alpha: Deny all tool calls
    rule_alpha = PolicyRule(
        policy_id="pol-alpha-deny-tools",
        name="Alpha Deny Tools",
        workspace_id="ws-tenant-alpha",
        action_type=ActionType.EXECUTE_TOOL.value,
        decision_if_matched=PolicyDecision.DENY,
    )
    await storage.save_policy_rule(rule_alpha)

    # Engine evaluating in ws-tenant-alpha
    engine_alpha = GovernanceEngine(gov_db, mode=EnforcementMode.ENFORCED)
    eval_alpha = await engine_alpha.evaluate_action(
        workspace_id="ws-tenant-alpha",
        agent_id="agent-alpha",
        action_type=ActionType.EXECUTE_TOOL.value,
        target="bash_runner",
    )
    assert eval_alpha.decision == PolicyDecision.DENY
    assert eval_alpha.matched_policy_id == "pol-alpha-deny-tools"

    # Engine evaluating identical action in ws-tenant-beta
    engine_beta = GovernanceEngine(gov_db, mode=EnforcementMode.ENFORCED)
    eval_beta = await engine_beta.evaluate_action(
        workspace_id="ws-tenant-beta",
        agent_id="agent-beta",
        action_type=ActionType.EXECUTE_TOOL.value,
        target="bash_runner",
    )
    # Should not be affected by Alpha's custom policy
    assert eval_beta.decision == PolicyDecision.ALLOW
    assert eval_beta.matched_policy_id != "pol-alpha-deny-tools"


# ===========================================================================
# Layer 5: E2E Test (Coding Agent Protected Merge Scenario)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_coding_agent_protected_merge_in_shadow_mode(gov_db: str):
    """E2E Scenario:
    1. Coding Agent requests to merge a Pull Request into 'main'.
    2. Governance Engine evaluates policy rules against protected branch.
    3. Engine evaluates decision as REQUIRE_APPROVAL.
    4. Because enforcement mode is SHADOW, effective_action_taken is ALLOWED_BY_SHADOW_MODE.
    5. Evaluation event is persisted to the audit ledger for governance visibility.
    """
    engine = GovernanceEngine(gov_db, mode=EnforcementMode.SHADOW)

    eval_result = await engine.evaluate_action(
        workspace_id="ws-prod-deploy",
        agent_id="agent-pr-bot-01",
        task_id="task-merge-pr-42",
        run_id="run-pipeline-88",
        action_type=ActionType.MERGE_PR.value,
        target="github.com/org/repo:main",
        cost_usd=0.02,
        context_metadata={"target_branch": "main", "pr_number": 42},
    )

    # Verification
    assert eval_result.decision == PolicyDecision.REQUIRE_APPROVAL
    assert eval_result.effective_action_taken == "ALLOWED_BY_SHADOW_MODE"
    assert eval_result.matched_policy_id == "pol-default-merge-pr"
    assert "requires approval" in eval_result.reason

    # Query storage audit record
    summary = await engine.get_shadow_evaluation_summary("ws-prod-deploy")
    assert summary["total_evaluations"] == 1
    assert summary["would_require_approval"] == 1
