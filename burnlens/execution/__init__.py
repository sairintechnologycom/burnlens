"""Phase 6: BL-AE-006 Assisted Execution (Human-Approved).

Provides safe, controlled execution of optimization recommendations via Git workflows.
Human remains the mandatory execution and merge authority.
"""
from __future__ import annotations

from burnlens.execution.adapter import (
    AutoMergeForbiddenError,
    GitHubExecutionAdapter,
    GitProviderClient,
    GitProviderError,
    MockGitHubClient,
    ProtectedBranchError,
)
from burnlens.execution.models import (
    PROTECTED_BRANCHES,
    ApprovalState,
    ApprovalToken,
    ExecutionBinding,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTimelineEvent,
)
from burnlens.execution.service import AssistedExecutionService
from burnlens.execution.storage import ExecutionStorage

__all__ = [
    "ApprovalState",
    "ApprovalToken",
    "AssistedExecutionService",
    "AutoMergeForbiddenError",
    "ExecutionBinding",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionStorage",
    "ExecutionTimelineEvent",
    "GitHubExecutionAdapter",
    "GitProviderClient",
    "GitProviderError",
    "MockGitHubClient",
    "ProtectedBranchError",
    "PROTECTED_BRANCHES",
]
