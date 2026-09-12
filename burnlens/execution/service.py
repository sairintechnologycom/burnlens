"""Phase 6: BL-AE-006 Assisted Execution Service.

Coordinates:
- Creation of cryptographically bound execution requests
- Human review & approval token issuance
- Replay prevention & idempotency verification
- Scope and target branch verification
- Execution via GitHub adapter (create branch, commit scoped files, open PR, record CI)
- Complete immutable audit timeline capture
- Strict enforcement of human authority (auto-merge strictly denied)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from burnlens.execution.adapter import (
    AutoMergeForbiddenError,
    GitHubExecutionAdapter,
    GitProviderError,
    ProtectedBranchError,
)
from burnlens.execution.models import (
    ApprovalToken,
    ExecutionBinding,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTimelineEvent,
)
from burnlens.execution.storage import ExecutionStorage

logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEY = "burnlens-assisted-execution-secret"


class AssistedExecutionService:
    """Orchestrator for human-approved assisted execution workflows."""

    def __init__(
        self,
        storage: ExecutionStorage,
        adapter: GitHubExecutionAdapter | None = None,
        secret_key: str = DEFAULT_SECRET_KEY,
    ) -> None:
        self.storage = storage
        self.adapter = adapter or GitHubExecutionAdapter()
        self.secret_key = secret_key

    def create_binding(
        self,
        request: ExecutionRequest,
        expires_in_seconds: int = 3600,
        nonce: str = "",
    ) -> ExecutionBinding:
        """Construct the cryptographic binding for an execution request."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=expires_in_seconds)
        payload_hash = request.compute_payload_hash()

        return ExecutionBinding(
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            task_id=request.task_id,
            recommendation_id=request.recommendation_id,
            repo=request.repo,
            base_branch=request.base_branch,
            target_branch=request.target_branch,
            scoped_files=request.scoped_files,
            change_payload_hash=payload_hash,
            expires_at=expires_at,
            nonce=nonce,
        )

    async def issue_approval(
        self,
        binding: ExecutionBinding,
        approver: str,
        token_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalToken:
        """Issue and record a cryptographically signed approval token."""
        token_id = token_id or f"appr-{uuid.uuid4().hex[:12]}"
        token = ApprovalToken.create(
            token_id=token_id,
            binding=binding,
            approver=approver,
            secret_key=self.secret_key,
            metadata=metadata or {},
        )
        await self.storage.save_approval_token(token)
        return token

    async def execute(
        self,
        request: ExecutionRequest,
        token: ApprovalToken,
        now: datetime | None = None,
    ) -> ExecutionResult:
        """Execute an approved execution request after complete verification."""
        if now is None:
            now = datetime.now(timezone.utc)

        # Step 1: Check Idempotency (replay prevention)
        existing = await self.storage.get_by_idempotency(request.workspace_id, request.idempotency_key)
        if existing:
            logger.info("Returning existing execution result for idempotency key: %s", request.idempotency_key)
            return existing

        timeline: list[ExecutionTimelineEvent] = []

        def record_stage(stage: str, msg: str, details: dict[str, Any] | None = None) -> None:
            ev = ExecutionTimelineEvent(
                event_id=f"ev-{uuid.uuid4().hex[:10]}",
                execution_id=request.execution_id,
                stage=stage,
                message=msg,
                details=details or {},
                timestamp=now or datetime.now(timezone.utc),
            )
            timeline.append(ev)

        record_stage("RECOMMENDED", f"Recommendation {request.recommendation_id} prepared for execution", {
            "agent_id": request.agent_id,
            "task_id": request.task_id,
            "repo": request.repo,
        })

        # Step 2: Multi-tenant workspace check
        if token.workspace_id != request.workspace_id:
            reason = f"TENANT_ISOLATION_VIOLATION: Token workspace {token.workspace_id} does not match request workspace {request.workspace_id}"
            record_stage("DENIED", reason)
            res = ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.DENIED,
                workspace_id=request.workspace_id,
                repo=request.repo,
                error_code="TENANT_ISOLATION_VIOLATION",
                error_message=reason,
                timeline=timeline,
                executed_at=now,
            )
            await self.storage.save_execution(
                res, request.agent_id, request.task_id, request.recommendation_id,
                request.base_branch, request.target_branch, request.idempotency_key
            )
            return res

        # Sync persisted consumed status if available
        db_token = await self.storage.get_approval_token(token.token_id, request.workspace_id)
        if db_token and db_token.consumed:
            token.consumed = True

        # Step 3: Compute current binding
        current_binding = ExecutionBinding(
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            task_id=request.task_id,
            recommendation_id=request.recommendation_id,
            repo=request.repo,
            base_branch=request.base_branch,
            target_branch=request.target_branch,
            scoped_files=request.scoped_files,
            change_payload_hash=request.compute_payload_hash(),
            expires_at=token.expires_at,
            nonce=token.metadata.get("nonce", ""),
        )
        current_binding_hash = current_binding.compute_hash()

        # Step 4: Validate Approval Token
        is_valid, validation_err = token.is_valid(
            current_binding_hash=current_binding_hash,
            now=now,
            secret_key=self.secret_key,
        )
        if not is_valid:
            record_stage("DENIED", validation_err)
            err_code = validation_err.split(":")[0].strip()
            res = ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.DENIED,
                workspace_id=request.workspace_id,
                repo=request.repo,
                error_code=err_code,
                error_message=validation_err,
                timeline=timeline,
                executed_at=now,
            )
            await self.storage.save_execution(
                res, request.agent_id, request.task_id, request.recommendation_id,
                request.base_branch, request.target_branch, request.idempotency_key
            )
            return res

        # Step 5: Scope & Target Branch Validation
        scope_ok, scope_err = request.validate_scope()
        if not scope_ok:
            record_stage("DENIED", scope_err)
            err_code = scope_err.split(":")[0].strip()
            res = ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.DENIED,
                workspace_id=request.workspace_id,
                repo=request.repo,
                error_code=err_code,
                error_message=scope_err,
                timeline=timeline,
                executed_at=now,
            )
            await self.storage.save_execution(
                res, request.agent_id, request.task_id, request.recommendation_id,
                request.base_branch, request.target_branch, request.idempotency_key
            )
            return res

        # Record human approval stage
        record_stage("APPROVAL_VERIFIED", f"Approved by {token.approver}", {
            "token_id": token.token_id,
            "approved_at": token.approved_at.isoformat(),
        })

        # Step 6: Mark token consumed to prevent duplicate reuse
        await self.storage.mark_token_consumed(token.token_id, now)

        # Step 7: Execute Git workflow operations via Adapter
        try:
            record_stage("EXECUTION_STARTED", f"Creating branch '{request.target_branch}'")
            branch_info = await self.adapter.create_branch(
                repo=request.repo,
                base_branch=request.base_branch,
                new_branch=request.target_branch,
            )
            record_stage("BRANCH_CREATED", f"Created branch '{request.target_branch}'", branch_info)

            # Commit scoped files
            commit_msg = (
                f"burnlens({request.recommendation_id}): apply optimization changes\n\n"
                f"Approved-by: {token.approver}\n"
                f"Task-ID: {request.task_id}\n"
                f"Agent-ID: {request.agent_id}"
            )
            commit_info = await self.adapter.commit_scoped_changes(
                repo=request.repo,
                branch=request.target_branch,
                files=request.changes,
                message=commit_msg,
            )
            commit_sha = commit_info.get("commit_sha")
            record_stage("FILES_COMMITTED", f"Committed {len(request.changes)} files ({commit_sha})", commit_info)

            # Open Pull Request
            pr_title = f"[BurnLens Optimization] {request.recommendation_id} - Scoped Changes"
            pr_body = (
                f"## BurnLens Assisted Execution\n\n"
                f"- **Recommendation**: `{request.recommendation_id}`\n"
                f"- **Agent**: `{request.agent_id}`\n"
                f"- **Task**: `{request.task_id}`\n"
                f"- **Approved By**: `{token.approver}`\n"
                f"- **Scoped Files**: {', '.join(request.scoped_files)}\n\n"
                f"> **Notice**: Auto-merge is disabled under BL-AE-006. "
                f"Human review and approval in GitHub is mandatory prior to merging."
            )
            pr_info = await self.adapter.open_pull_request(
                repo=request.repo,
                title=pr_title,
                body=pr_body,
                head_branch=request.target_branch,
                base_branch=request.base_branch,
            )
            pr_number = pr_info.get("pr_number")
            pr_url = pr_info.get("html_url")
            record_stage("PR_OPENED", f"Opened PR #{pr_number}", pr_info)

            # Record CI status
            ci_status = await self.adapter.record_ci_status(request.repo, commit_sha or request.target_branch)
            record_stage("CI_RECORDED", f"Initial CI status: {ci_status}", {"ci_status": ci_status})

            # Completed successfully
            record_stage("COMPLETED", "Execution completed safely; PR remains open and unmerged", {
                "pr_number": pr_number,
                "is_unmerged": True,
            })

            result = ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.COMPLETED,
                workspace_id=request.workspace_id,
                repo=request.repo,
                branch_name=request.target_branch,
                commit_sha=commit_sha,
                pr_number=pr_number,
                pr_url=pr_url,
                ci_status=ci_status,
                is_unmerged=True,  # Human authority remains mandatory
                idempotent_replay=False,
                timeline=timeline,
                executed_at=now,
            )

        except (ProtectedBranchError, AutoMergeForbiddenError, GitProviderError, Exception) as exc:
            logger.exception("Assisted execution failed: %s", exc)
            record_stage("FAILED", str(exc), {"error_type": type(exc).__name__})
            result = ExecutionResult(
                execution_id=request.execution_id,
                status=ExecutionStatus.FAILED,
                workspace_id=request.workspace_id,
                repo=request.repo,
                error_code=type(exc).__name__,
                error_message=str(exc),
                timeline=timeline,
                executed_at=now,
            )

        await self.storage.save_execution(
            result,
            request.agent_id,
            request.task_id,
            request.recommendation_id,
            request.base_branch,
            request.target_branch,
            request.idempotency_key,
        )
        return result
