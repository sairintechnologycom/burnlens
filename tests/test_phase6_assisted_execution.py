"""Tests for Phase 6: BL-AE-006 Assisted Execution (Human-Approved).

5-Layer Test Pyramid:
- Layer 1 (Unit): ExecutionBinding deterministic hashing, tamper detection, signature verification, scope validation
- Layer 2 (Contract): ExecutionStatus, ExecutionResult, ApprovalToken schemas, lifecycle contracts
- Layer 3 (Integration): Multi-step execution via GitHub adapter, branch creation, commit, PR opening, CI recording, audit trail
- Layer 4 (Security): Negative security tests (expired approval, scope violation, repo change, payload tampering,
                      protected branch push, auto-merge denial, replay prevention, multi-tenant isolation)
- Layer 5 (E2E): Full Golden Journey: Vulnerable dependency fix workflow with mandatory human approval
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from burnlens.execution.adapter import (
    AutoMergeForbiddenError,
    GitHubExecutionAdapter,
    MockGitHubClient,
    ProtectedBranchError,
)
from burnlens.execution.models import (
    ApprovalState,
    ApprovalToken,
    ExecutionBinding,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTimelineEvent,
    PROTECTED_BRANCHES,
)
from burnlens.execution.service import AssistedExecutionService
from burnlens.execution.storage import ExecutionStorage
from burnlens.storage.database import init_db


@pytest.fixture
async def exec_storage(tmp_path: Path) -> ExecutionStorage:
    """Provide initialized SQLite database with execution schema."""
    db_path = str(tmp_path / "execution_test.db")
    await init_db(db_path)
    storage = ExecutionStorage(db_path)
    await storage.init_execution_schema()
    return storage


@pytest.fixture
def mock_gh() -> MockGitHubClient:
    """Provide seeded mock GitHub client."""
    client = MockGitHubClient()
    client.seed_repo("acme/backend", default_branch="main", initial_sha="sha-init-100")
    return client


# ===========================================================================
# Layer 1: Unit Tests (Binding, Token, Scope, and Tamper Detection)
# ===========================================================================

def test_layer1_unit_binding_hash_determinism_and_tamper_detection():
    """Binding hash must be deterministic and sensitive to every attribute."""
    expiry = datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc)
    binding = ExecutionBinding(
        workspace_id="ws-prod",
        agent_id="agent-coder-1",
        task_id="task-fix-42",
        recommendation_id="rec-opt-99",
        repo="acme/backend",
        base_branch="main",
        target_branch="burnlens/opt-fix-42",
        scoped_files=["pyproject.toml", "poetry.lock"],
        change_payload_hash="hash-abc-123",
        expires_at=expiry,
    )
    initial_hash = binding.compute_hash()
    assert len(initial_hash) == 64
    # Recomputing gives same hash
    assert binding.compute_hash() == initial_hash

    # Tampering: change repo
    binding_tampered_repo = ExecutionBinding(
        workspace_id=binding.workspace_id,
        agent_id=binding.agent_id,
        task_id=binding.task_id,
        recommendation_id=binding.recommendation_id,
        repo="acme/infrastructure",  # altered
        base_branch=binding.base_branch,
        target_branch=binding.target_branch,
        scoped_files=binding.scoped_files,
        change_payload_hash=binding.change_payload_hash,
        expires_at=binding.expires_at,
    )
    assert binding_tampered_repo.compute_hash() != initial_hash

    # Tampering: change scoped files
    binding_tampered_scope = ExecutionBinding(
        workspace_id=binding.workspace_id,
        agent_id=binding.agent_id,
        task_id=binding.task_id,
        recommendation_id=binding.recommendation_id,
        repo=binding.repo,
        base_branch=binding.base_branch,
        target_branch=binding.target_branch,
        scoped_files=["pyproject.toml", "secrets.env"],  # altered
        change_payload_hash=binding.change_payload_hash,
        expires_at=binding.expires_at,
    )
    assert binding_tampered_scope.compute_hash() != initial_hash


def test_layer1_unit_approval_token_verification_and_expiry():
    """ApprovalToken must cryptographically verify signature, binding match, and expiry."""
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    binding = ExecutionBinding(
        workspace_id="ws-prod",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        base_branch="main",
        target_branch="burnlens/opt-1",
        scoped_files=["requirements.txt"],
        change_payload_hash="hash-reqs",
        expires_at=expiry,
    )
    token = ApprovalToken.create(
        token_id="tok-001",
        binding=binding,
        approver="alice@company.com",
    )

    # Valid check
    valid, msg = token.is_valid(binding.compute_hash())
    assert valid is True
    assert msg == "OK"

    # Mismatched binding hash
    valid_bad_hash, msg_bad = token.is_valid("hash-different-123")
    assert valid_bad_hash is False
    assert "APPROVAL_INVALIDATED" in msg_bad

    # Expired token
    past_time = expiry + timedelta(minutes=5)
    valid_expired, msg_exp = token.is_valid(binding.compute_hash(), now=past_time)
    assert valid_expired is False
    assert "APPROVAL_EXPIRED" in msg_exp

    # Consumed token
    token.consumed = True
    valid_consumed, msg_cons = token.is_valid(binding.compute_hash())
    assert valid_consumed is False
    assert "APPROVAL_ALREADY_CONSUMED" in msg_cons


def test_layer1_unit_request_scope_and_protected_branch_validation():
    """ExecutionRequest must reject files outside scope and direct pushes to protected branches."""
    # 1. Allowed scoped file
    req_valid = ExecutionRequest(
        execution_id="exec-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/update-dep",
        scoped_files=["config/*.json", "src/models.py"],
        changes={"config/app.json": '{"timeout": 30}', "src/models.py": "# updated"},
        idempotency_key="idemp-1",
    )
    ok, err = req_valid.validate_scope()
    assert ok is True

    # 2. Scope violation: modifying unauthorized file
    req_unauthorized = ExecutionRequest(
        execution_id="exec-2",
        workspace_id="ws-1",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/update-dep",
        scoped_files=["config/*.json"],
        changes={"config/app.json": "{}", "infra/iam.tf": "resource aws_iam..."},
        idempotency_key="idemp-2",
    )
    ok_unauth, err_unauth = req_unauthorized.validate_scope()
    assert ok_unauth is False
    assert "SCOPE_VIOLATION" in err_unauth

    # 3. Protected branch direct target violation
    for prot_branch in PROTECTED_BRANCHES:
        req_prot = ExecutionRequest(
            execution_id=f"exec-prot-{prot_branch}",
            workspace_id="ws-1",
            agent_id="agent-1",
            task_id="task-1",
            recommendation_id="rec-1",
            repo="acme/backend",
            target_branch=prot_branch,
            scoped_files=["config/*.json"],
            changes={"config/app.json": "{}"},
            idempotency_key=f"idemp-{prot_branch}",
        )
        ok_prot, err_prot = req_prot.validate_scope()
        assert ok_prot is False
        assert "PROTECTED_BRANCH_VIOLATION" in err_prot


# ===========================================================================
# Layer 2: Contract Tests (State Machine & Schemas)
# ===========================================================================

def test_layer2_contract_execution_result_schema():
    """ExecutionResult must satisfy mandatory contract including unmerged state and timeline."""
    res = ExecutionResult(
        execution_id="exec-contract-1",
        status=ExecutionStatus.COMPLETED,
        workspace_id="ws-test",
        repo="acme/service",
        branch_name="burnlens/opt-branch",
        commit_sha="sha-9999",
        pr_number=101,
        pr_url="https://github.com/acme/service/pull/101",
        ci_status="pending",
        is_unmerged=True,
        timeline=[
            ExecutionTimelineEvent(
                event_id="ev-1",
                execution_id="exec-contract-1",
                stage="PR_OPENED",
                message="PR opened",
            )
        ],
    )
    d = res.to_dict()
    assert d["execution_id"] == "exec-contract-1"
    assert d["status"] == "COMPLETED"
    assert d["is_unmerged"] is True  # Mandatory: human authority retained
    assert len(d["timeline"]) == 1
    assert d["timeline"][0]["stage"] == "PR_OPENED"


# ===========================================================================
# Layer 3: Integration Tests (End-to-End Adapter & Storage Coordination)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_assisted_execution_lifecycle(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Assisted execution must coordinate approval, branch creation, commit, PR, CI, and audit storage."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req = ExecutionRequest(
        execution_id="exec-integ-1",
        workspace_id="ws-main",
        agent_id="agent-finops-1",
        task_id="task-caching-opt",
        recommendation_id="rec-cache-123",
        repo="acme/backend",
        base_branch="main",
        target_branch="burnlens/caching-opt",
        scoped_files=["src/prompt_templates.py"],
        changes={"src/prompt_templates.py": "CACHE_CONTROL = {'type': 'ephemeral'}"},
        idempotency_key="idemp-integ-1",
    )

    # Human grants approval
    binding = service.create_binding(req, expires_in_seconds=1800)
    token = await service.issue_approval(binding, approver="security-officer@acme.com")

    # Service executes
    result = await service.execute(req, token)

    assert result.status == ExecutionStatus.COMPLETED
    assert result.branch_name == "burnlens/caching-opt"
    assert result.commit_sha is not None
    assert result.pr_number == 101
    assert result.pr_url == "https://github.com/acme/backend/pull/101"
    assert result.is_unmerged is True
    assert result.ci_status in ("pending", "success")

    # Verify timeline events stored in SQLite
    timeline = await exec_storage.get_timeline("exec-integ-1")
    stages = [ev.stage for ev in timeline]
    assert "RECOMMENDED" in stages
    assert "APPROVAL_VERIFIED" in stages
    assert "BRANCH_CREATED" in stages
    assert "FILES_COMMITTED" in stages
    assert "PR_OPENED" in stages
    assert "CI_RECORDED" in stages
    assert "COMPLETED" in stages

    # Check mock git state
    assert "burnlens/caching-opt" in mock_gh.branches["acme/backend"]
    prs = mock_gh.pull_requests["acme/backend"]
    assert len(prs) == 1
    assert prs[0]["pr_number"] == 101
    assert prs[0]["merged"] is False


# ===========================================================================
# Layer 4: Security Tests (Negative Security & Policy Invariants)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_negative_expired_approval_denied(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Expired approval must be strictly DENIED without mutating git state."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req = ExecutionRequest(
        execution_id="exec-sec-exp",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-exp",
        scoped_files=["src/app.py"],
        changes={"src/app.py": "x = 1"},
        idempotency_key="idemp-sec-exp",
    )
    binding = service.create_binding(req, expires_in_seconds=10)
    token = await service.issue_approval(binding, approver="bob@acme.com")

    # Simulate execution after expiry
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    result = await service.execute(req, token, now=future_time)

    assert result.status == ExecutionStatus.DENIED
    assert result.error_code == "APPROVAL_EXPIRED"
    assert "APPROVAL_EXPIRED" in (result.error_message or "")
    # Git state must remain untouched
    assert "burnlens/opt-exp" not in mock_gh.branches["acme/backend"]


@pytest.mark.asyncio
async def test_layer4_security_negative_repo_or_scope_changed_denied(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Mutating target repo or scoped files after approval invalidates token binding and is DENIED."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req = ExecutionRequest(
        execution_id="exec-sec-tamper",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-1",
        scoped_files=["config/settings.json"],
        changes={"config/settings.json": "{}"},
        idempotency_key="idemp-sec-tamper",
    )
    binding = service.create_binding(req, expires_in_seconds=3600)
    token = await service.issue_approval(binding, approver="alice@acme.com")

    # Attack scenario: Agent attempts to apply changes to unauthorized repo
    tampered_req = ExecutionRequest(
        execution_id="exec-sec-tamper",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/infrastructure-prod",  # TAMPERED
        target_branch="burnlens/opt-1",
        scoped_files=["config/settings.json"],
        changes={"config/settings.json": "{}"},
        idempotency_key="idemp-sec-tamper",
    )
    result = await service.execute(tampered_req, token)

    assert result.status == ExecutionStatus.DENIED
    assert result.error_code == "APPROVAL_INVALIDATED"


@pytest.mark.asyncio
async def test_layer4_security_negative_scope_violation_denied(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Attempting to modify files outside scoped files is rejected with SCOPE_VIOLATION."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req = ExecutionRequest(
        execution_id="exec-sec-scope",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-1",
        scoped_files=["src/utils.py"],
        changes={"src/utils.py": "a = 1", "/etc/shadow": "malicious"},  # Violation
        idempotency_key="idemp-sec-scope",
    )
    binding = service.create_binding(req, expires_in_seconds=3600)
    token = await service.issue_approval(binding, approver="alice@acme.com")

    result = await service.execute(req, token)

    assert result.status == ExecutionStatus.DENIED
    assert result.error_code == "SCOPE_VIOLATION"


@pytest.mark.asyncio
async def test_layer4_security_negative_auto_merge_strictly_forbidden(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Auto-merging pull requests is strictly forbidden; human review is mandatory."""
    adapter = GitHubExecutionAdapter(mock_gh)
    with pytest.raises(AutoMergeForbiddenError):
        await adapter.auto_merge_pr("acme/backend", pr_number=101)


@pytest.mark.asyncio
async def test_layer4_security_replay_prevention_and_idempotency(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Executing twice with the same idempotency key returns cached result without duplicate PR."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req = ExecutionRequest(
        execution_id="exec-replay-1",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-replay",
        scoped_files=["config.yaml"],
        changes={"config.yaml": "retries: 2"},
        idempotency_key="idemp-replay-key-001",
    )
    binding = service.create_binding(req, expires_in_seconds=3600)
    token = await service.issue_approval(binding, approver="alice@acme.com")

    # First execution: Success
    res1 = await service.execute(req, token)
    assert res1.status == ExecutionStatus.COMPLETED
    assert res1.idempotent_replay is False

    # Second execution: Replay detected -> Returns cached result immediately, NO duplicate PR
    res2 = await service.execute(req, token)
    assert res2.status == ExecutionStatus.COMPLETED
    assert res2.idempotent_replay is True
    assert res2.pr_number == res1.pr_number

    # Pull requests in mock GitHub should be exactly 1
    assert len(mock_gh.pull_requests["acme/backend"]) == 1

    # Using the consumed token on a NEW idempotency key must be DENIED (consumed token reuse)
    req_new_key = ExecutionRequest(
        execution_id="exec-replay-2",
        workspace_id="ws-main",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-replay",
        scoped_files=["config.yaml"],
        changes={"config.yaml": "retries: 2"},
        idempotency_key="idemp-new-key-002",
    )
    res3 = await service.execute(req_new_key, token)
    assert res3.status == ExecutionStatus.DENIED
    assert res3.error_code == "APPROVAL_ALREADY_CONSUMED"


@pytest.mark.asyncio
async def test_layer4_security_tenant_isolation(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Token approved in Workspace Alpha cannot execute in Workspace Beta."""
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    req_alpha = ExecutionRequest(
        execution_id="exec-alpha",
        workspace_id="ws-alpha",
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-tenant",
        scoped_files=["config.yaml"],
        changes={"config.yaml": "retries: 2"},
        idempotency_key="idemp-alpha",
    )
    binding_alpha = service.create_binding(req_alpha)
    token_alpha = await service.issue_approval(binding_alpha, approver="alice@acme.com")

    # Cross-tenant execution request
    req_beta = ExecutionRequest(
        execution_id="exec-beta",
        workspace_id="ws-beta",  # Different workspace!
        agent_id="agent-1",
        task_id="task-1",
        recommendation_id="rec-1",
        repo="acme/backend",
        target_branch="burnlens/opt-tenant",
        scoped_files=["config.yaml"],
        changes={"config.yaml": "retries: 2"},
        idempotency_key="idemp-beta",
    )
    result = await service.execute(req_beta, token_alpha)
    assert result.status == ExecutionStatus.DENIED
    assert result.error_code == "TENANT_ISOLATION_VIOLATION"


# ===========================================================================
# Layer 5: E2E Golden Coding Agent Journey (Vulnerable Dependency Fix)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_coding_agent_journey(
    exec_storage: ExecutionStorage, mock_gh: MockGitHubClient
):
    """Golden End-to-End Journey (Plan Section 8):

    Scenario: Coding agent fixes a vulnerable dependency:
    1. Recommendation generated
    2. Human reviews and issues approval token
    3. Execution adapter creates branch
    4. Code changes committed to branch
    5. PR opened with full justification
    6. CI status recorded
    7. PR remains strictly unmerged
    8. Audit timeline complete and verified
    """
    adapter = GitHubExecutionAdapter(mock_gh)
    service = AssistedExecutionService(exec_storage, adapter)

    # 1. Recommendation prepared for coding agent
    req = ExecutionRequest(
        execution_id="exec-golden-cve-fix",
        workspace_id="ws-acme-corp",
        agent_id="codex-security-fixer-v2.3",
        task_id="task-cve-2026-9999",
        recommendation_id="rec-cve-fix-requests",
        repo="acme/backend",
        base_branch="main",
        target_branch="burnlens/fix-cve-2026-9999",
        scoped_files=["requirements.txt"],
        changes={"requirements.txt": "requests>=2.32.3\nurllib3>=2.2.2\n"},
        idempotency_key="idemp-cve-fix-reqs",
    )

    # 2. Human reviews and approves
    binding = service.create_binding(req, expires_in_seconds=3600)
    token = await service.issue_approval(
        binding=binding,
        approver="lead-security-engineer@acme.com",
        metadata={"jira_ticket": "SEC-4091", "cve_id": "CVE-2026-9999"},
    )

    # 3. Execution
    result = await service.execute(req, token)

    # 4. Invariant verifications
    assert result.status == ExecutionStatus.COMPLETED
    assert result.branch_name == "burnlens/fix-cve-2026-9999"
    assert result.commit_sha is not None
    assert result.pr_number is not None
    assert result.is_unmerged is True  # Human authority preserved!
    assert result.ci_status in ("pending", "success")

    # Check Git provider state
    prs = mock_gh.pull_requests["acme/backend"]
    assert len(prs) == 1
    golden_pr = prs[0]
    assert golden_pr["head_branch"] == "burnlens/fix-cve-2026-9999"
    assert golden_pr["base_branch"] == "main"
    assert golden_pr["merged"] is False
    assert "CVE-2026-9999" in golden_pr["title"] or "rec-cve-fix-requests" in golden_pr["title"]
    assert "Auto-merge is disabled" in golden_pr["body"]

    # Audit timeline complete
    timeline = await exec_storage.get_timeline("exec-golden-cve-fix")
    stage_sequence = [ev.stage for ev in timeline]
    expected_sequence = [
        "RECOMMENDED",
        "APPROVAL_VERIFIED",
        "EXECUTION_STARTED",
        "BRANCH_CREATED",
        "FILES_COMMITTED",
        "PR_OPENED",
        "CI_RECORDED",
        "COMPLETED",
    ]
    for stage in expected_sequence:
        assert stage in stage_sequence
