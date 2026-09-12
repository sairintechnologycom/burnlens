"""Phase 7: BL-AE-007 Runtime Guardrails Failure Detectors.

Deterministic, explainable detection of:
- Retry storms
- Hard budget exhaustion
- Runaway task loops
- Repeated tool execution failures
- Forbidden actions
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from burnlens.guardrails.models import (
    GuardrailDecision,
    GuardrailDecisionType,
    GuardrailFailureType,
    GuardrailPolicy,
    RuntimeTelemetryEvent,
    TaskLifecycleState,
)

logger = logging.getLogger(__name__)


class GuardrailDetector:
    """Deterministic failure condition detector."""

    @staticmethod
    def detect_forbidden_action(action_type: str, forbidden_actions: list[str]) -> tuple[bool, str]:
        """Check if action is explicitly forbidden."""
        act_clean = action_type.strip().lower()
        for forbidden in forbidden_actions:
            if act_clean == forbidden.strip().lower():
                return True, f"Action '{action_type}' is prohibited by security policy (forbidden list)."
        return False, ""

    @staticmethod
    def detect_hard_budget_exceeded(current_cost: float, max_budget: float) -> tuple[bool, str]:
        """Check if cumulative task spend exceeds hard budget cap."""
        if current_cost > max_budget:
            return True, f"Hard budget of ${max_budget:.2f} exceeded. Total task spend reached ${current_cost:.2f}."
        return False, ""

    @staticmethod
    def detect_retry_storm(retries: int, max_retries: int) -> tuple[bool, str]:
        """Check if retry count exceeds tolerable threshold."""
        if retries >= max_retries:
            return True, f"Retry storm detected: task accumulated {retries} retries (threshold: {max_retries})."
        return False, ""

    @staticmethod
    def detect_repeated_tool_errors(consecutive_errors: int, max_consecutive_errors: int) -> tuple[bool, str]:
        """Check if consecutive tool errors exceed tolerable threshold."""
        if consecutive_errors >= max_consecutive_errors:
            return True, f"Repeated tool failure detected: {consecutive_errors} consecutive errors (threshold: {max_consecutive_errors})."
        return False, ""

    @staticmethod
    def detect_runaway_task(request_count: int, max_requests: int) -> tuple[bool, str]:
        """Check if total task requests exceed runaway loop threshold."""
        if request_count >= max_requests:
            return True, f"Runaway task loop detected: accumulated {request_count} requests without completion (threshold: {max_requests})."
        return False, ""

    @classmethod
    def evaluate(
        cls,
        telemetry: RuntimeTelemetryEvent,
        task_metrics: dict[str, Any],
        policy: GuardrailPolicy,
    ) -> GuardrailDecision:
        """Evaluate incoming telemetry and accumulated task metrics against policy.

        Precedence order:
        1. FORBIDDEN_ACTION -> DENY
        2. HARD_BUDGET_EXCEEDED -> STOP
        3. RETRY_STORM -> PAUSE
        4. REPEATED_TOOL_ERROR -> PAUSE
        5. RUNAWAY_TASK -> PAUSE
        6. In-bounds -> ALLOW
        """
        now = datetime.now(timezone.utc)
        curr_cost = task_metrics.get("total_cost_usd", 0.0) + telemetry.cost_usd
        retries = task_metrics.get("retry_count", 0) + (1 if telemetry.is_retry else 0)
        tool_errs = task_metrics.get("consecutive_tool_errors", 0) + (1 if telemetry.is_tool_error else 0)
        req_count = task_metrics.get("request_count", 0) + 1

        metrics_snapshot = {
            "total_cost_usd": round(curr_cost, 4),
            "retry_count": retries,
            "consecutive_tool_errors": tool_errs,
            "request_count": req_count,
            "action_type": telemetry.action_type,
        }
        threshold_snapshot = {
            "hard_budget_usd": policy.hard_budget_usd,
            "max_retries": policy.max_retries,
            "max_consecutive_tool_errors": policy.max_consecutive_tool_errors,
            "max_task_requests": policy.max_task_requests,
            "forbidden_actions": policy.forbidden_actions,
        }

        # 1. Check Forbidden Action
        is_forbidden, f_reason = cls.detect_forbidden_action(telemetry.action_type, policy.forbidden_actions)
        if is_forbidden:
            return GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=telemetry.workspace_id,
                agent_id=telemetry.agent_id,
                task_id=telemetry.task_id,
                decision=GuardrailDecisionType.DENY,
                failure_type=GuardrailFailureType.FORBIDDEN_ACTION,
                reason=f_reason,
                current_metrics=metrics_snapshot,
                threshold=threshold_snapshot,
                evaluated_at=now,
            )

        # 2. Check Hard Budget Cap
        is_budget_exceeded, b_reason = cls.detect_hard_budget_exceeded(curr_cost, policy.hard_budget_usd)
        if is_budget_exceeded:
            return GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=telemetry.workspace_id,
                agent_id=telemetry.agent_id,
                task_id=telemetry.task_id,
                decision=GuardrailDecisionType.STOP,
                failure_type=GuardrailFailureType.HARD_BUDGET_EXCEEDED,
                reason=b_reason,
                current_metrics=metrics_snapshot,
                threshold=threshold_snapshot,
                evaluated_at=now,
            )

        # 3. Check Retry Storm
        is_retry_storm, r_reason = cls.detect_retry_storm(retries, policy.max_retries)
        if is_retry_storm:
            return GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=telemetry.workspace_id,
                agent_id=telemetry.agent_id,
                task_id=telemetry.task_id,
                decision=GuardrailDecisionType.PAUSE,
                failure_type=GuardrailFailureType.RETRY_STORM,
                reason=r_reason,
                current_metrics=metrics_snapshot,
                threshold=threshold_snapshot,
                evaluated_at=now,
            )

        # 4. Check Repeated Tool Errors
        is_tool_err_loop, t_reason = cls.detect_repeated_tool_errors(tool_errs, policy.max_consecutive_tool_errors)
        if is_tool_err_loop:
            return GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=telemetry.workspace_id,
                agent_id=telemetry.agent_id,
                task_id=telemetry.task_id,
                decision=GuardrailDecisionType.PAUSE,
                failure_type=GuardrailFailureType.REPEATED_TOOL_ERROR,
                reason=t_reason,
                current_metrics=metrics_snapshot,
                threshold=threshold_snapshot,
                evaluated_at=now,
            )

        # 5. Check Runaway Task Loop
        is_runaway, run_reason = cls.detect_runaway_task(req_count, policy.max_task_requests)
        if is_runaway:
            return GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=telemetry.workspace_id,
                agent_id=telemetry.agent_id,
                task_id=telemetry.task_id,
                decision=GuardrailDecisionType.PAUSE,
                failure_type=GuardrailFailureType.RUNAWAY_TASK,
                reason=run_reason,
                current_metrics=metrics_snapshot,
                threshold=threshold_snapshot,
                evaluated_at=now,
            )

        # 6. In-bounds normal operation
        return GuardrailDecision(
            decision_id=f"dec-{uuid.uuid4().hex[:12]}",
            workspace_id=telemetry.workspace_id,
            agent_id=telemetry.agent_id,
            task_id=telemetry.task_id,
            decision=GuardrailDecisionType.ALLOW,
            failure_type=GuardrailFailureType.NONE,
            reason="Telemetry within normal operational and economic boundaries.",
            current_metrics=metrics_snapshot,
            threshold=threshold_snapshot,
            evaluated_at=now,
        )
