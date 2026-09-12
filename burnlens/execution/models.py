"""Phase 6: BL-AE-006 Assisted Execution (Human-Approved) Data Models.

Defines:
- ExecutionStatus: State of an assisted execution job.
- ApprovalState: Lifecycle state of a human approval.
- ExecutionBinding: Cryptographic/logical binding tying agent, task, action, resource, scope, and expiry.
- ApprovalToken: Cryptographically verifiable, time-bounded approval token.
- ExecutionRequest: Proposed coding workflow change payload with explicit file scopes and idempotency keys.
- ExecutionTimelineEvent: Auditable lifecycle events in the execution trail.
- ExecutionResult: Outcome record of branch creation, file commits, PR opening, and CI recording.
"""
from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


PROTECTED_BRANCHES = frozenset({"main", "master", "prod", "production", "release"})


class ExecutionStatus(str, Enum):
    """Lifecycle status of an execution."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    REJECTED = "REJECTED"


class ApprovalState(str, Enum):
    """Lifecycle state of an approval."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass
class ExecutionBinding:
    """Cryptographically ties approval parameters together.

    Any mutation of workspace, agent, task, recommendation, repo, base_branch,
    target_branch, scoped_files, change payload, or expiry invalidates the binding.
    """

    workspace_id: str
    agent_id: str
    task_id: str
    recommendation_id: str
    repo: str
    base_branch: str
    target_branch: str
    scoped_files: list[str]
    change_payload_hash: str
    expires_at: datetime
    nonce: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 fingerprint over all canonical parameters."""
        sorted_files = sorted(self.scoped_files)
        files_str = ",".join(sorted_files)
        exp_str = self.expires_at.astimezone(timezone.utc).isoformat()
        payload = (
            f"{self.workspace_id}|{self.agent_id}|{self.task_id}|{self.recommendation_id}|"
            f"{self.repo}|{self.base_branch}|{self.target_branch}|{files_str}|"
            f"{self.change_payload_hash}|{exp_str}|{self.nonce}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ApprovalToken:
    """Time-bounded approval token issued by an authorized human."""

    token_id: str
    binding_hash: str
    workspace_id: str
    approver: str
    approved_at: datetime
    expires_at: datetime
    signature: str
    consumed: bool = False
    consumed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        token_id: str,
        binding: ExecutionBinding,
        approver: str,
        secret_key: str = "burnlens-assisted-execution-secret",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalToken:
        """Create and cryptographically sign an approval token for a binding."""
        binding_hash = binding.compute_hash()
        now = datetime.now(timezone.utc)
        sig_data = f"{token_id}:{binding_hash}:{binding.workspace_id}:{approver}:{binding.expires_at.isoformat()}"
        signature = hmac.new(secret_key.encode("utf-8"), sig_data.encode("utf-8"), hashlib.sha256).hexdigest()
        return cls(
            token_id=token_id,
            binding_hash=binding_hash,
            workspace_id=binding.workspace_id,
            approver=approver,
            approved_at=now,
            expires_at=binding.expires_at,
            signature=signature,
            metadata=metadata or {},
        )

    def is_valid(
        self,
        current_binding_hash: str,
        now: datetime | None = None,
        secret_key: str = "burnlens-assisted-execution-secret",
    ) -> tuple[bool, str]:
        """Validate token integrity, binding, and expiry."""
        if now is None:
            now = datetime.now(timezone.utc)

        # Check signature integrity
        sig_data = f"{self.token_id}:{self.binding_hash}:{self.workspace_id}:{self.approver}:{self.expires_at.isoformat()}"
        expected_sig = hmac.new(secret_key.encode("utf-8"), sig_data.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(self.signature, expected_sig):
            return False, "APPROVAL_INVALIDATED: Invalid approval signature"

        # Check binding match
        if self.binding_hash != current_binding_hash:
            return False, "APPROVAL_INVALIDATED: Scope, target, or change payload modified after approval"

        # Check expiry
        if now > self.expires_at:
            return False, f"APPROVAL_EXPIRED: Token expired at {self.expires_at.isoformat()}"

        # Check replay / consumption
        if self.consumed:
            return False, "APPROVAL_ALREADY_CONSUMED: Token was already used for execution"

        return True, "OK"


@dataclass
class ExecutionRequest:
    """Requested code change execution payload."""

    execution_id: str
    workspace_id: str
    agent_id: str
    task_id: str
    recommendation_id: str
    repo: str
    target_branch: str
    scoped_files: list[str]
    changes: dict[str, str]  # path -> content
    idempotency_key: str
    base_branch: str = "main"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_payload_hash(self) -> str:
        """Compute deterministic hash of the proposed code changes."""
        canonical_changes = sorted((k, v) for k, v in self.changes.items())
        serialized = json.dumps(canonical_changes, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def validate_scope(self) -> tuple[bool, str]:
        """Verify that proposed changes strictly adhere to scoped files and branches."""
        # 1. Direct push to protected branches is forbidden
        target_clean = self.target_branch.strip().lower()
        if target_clean in PROTECTED_BRANCHES:
            return (
                False,
                f"PROTECTED_BRANCH_VIOLATION: Direct execution targeting protected branch '{self.target_branch}' is prohibited.",
            )

        # 2. File scope validation
        for changed_file in self.changes.keys():
            matched = any(
                fnmatch.fnmatch(changed_file, pattern)
                for pattern in self.scoped_files
            )
            if not matched:
                return (
                    False,
                    f"SCOPE_VIOLATION: File '{changed_file}' is not permitted by scoped_files: {self.scoped_files}",
                )

        return True, "OK"


@dataclass
class ExecutionTimelineEvent:
    """Audit log entry in the execution lifecycle."""

    event_id: str
    execution_id: str
    stage: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "stage": self.stage,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ExecutionResult:
    """Outcome of an assisted execution."""

    execution_id: str
    status: ExecutionStatus
    workspace_id: str
    repo: str
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    ci_status: str | None = None
    is_unmerged: bool = True  # Mandatory: PR remains unmerged, human remains execution authority
    idempotent_replay: bool = False
    error_code: str | None = None
    error_message: str | None = None
    timeline: list[ExecutionTimelineEvent] = field(default_factory=list)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "workspace_id": self.workspace_id,
            "repo": self.repo,
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "ci_status": self.ci_status,
            "is_unmerged": self.is_unmerged,
            "idempotent_replay": self.idempotent_replay,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "timeline": [e.to_dict() for e in self.timeline],
            "executed_at": self.executed_at.isoformat(),
        }
