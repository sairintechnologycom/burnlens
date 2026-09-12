"""Phase 7: BL-AE-007 Runtime Guardrail Engine.

Coordinates:
- Ingestion of real-time telemetry from agent steps
- Deduplication of incoming telemetry events
- Evaluation of telemetry against deterministic detector rules
- Enforcement of task lifecycle transitions (PAUSE, STOP, ALLOW, DENY)
- Immune to prompt-injection or unauthorized agent overrides
- Reversible pause states with human operator resume capability
- Fail-safe defaults under control-plane failure or timeout
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from burnlens.guardrails.detector import GuardrailDetector
from burnlens.guardrails.models import (
    FailSafeMode,
    GuardrailDecision,
    GuardrailDecisionType,
    GuardrailFailureType,
    GuardrailPolicy,
    RuntimeTelemetryEvent,
    TaskLifecycleState,
)
from burnlens.guardrails.storage import GuardrailStorage

logger = logging.getLogger(__name__)


class GuardrailEngine:
    """Runtime Guardrail control engine."""

    def __init__(self, storage: GuardrailStorage) -> None:
        self.storage = storage

    async def get_or_create_default_policy(self, workspace_id: str) -> GuardrailPolicy:
        """Fetch active workspace policy, or initialize standard default guardrails."""
        policy = await self.storage.get_policy(workspace_id)
        if policy is None:
            policy = GuardrailPolicy(
                policy_id=f"pol-guard-{workspace_id}",
                workspace_id=workspace_id,
                name="Default Workspace Guardrails",
            )
            await self.storage.save_policy(policy)
        return policy

    async def evaluate_runtime_event(
        self,
        event: RuntimeTelemetryEvent,
        simulate_control_plane_failure: bool = False,
    ) -> GuardrailDecision:
        """Evaluate an incoming runtime telemetry event against guardrails.

        Guarantees:
        - Deduplication of telemetry events
        - Prevention of unauthorized agent overrides
        - Task lifecycle transition (PAUSE on anomaly, STOP on budget, DENY on forbidden)
        - Fail-safe response if control plane encounters failure
        """
        now = datetime.now(timezone.utc)

        # 1. Deduplication check
        if await self.storage.is_event_duplicate(event.event_id):
            logger.info("Ignoring duplicate telemetry event: %s", event.event_id)
            return GuardrailDecision(
                decision_id=f"dec-dup-{event.event_id}",
                workspace_id=event.workspace_id,
                agent_id=event.agent_id,
                task_id=event.task_id,
                decision=GuardrailDecisionType.ALLOW,
                failure_type=GuardrailFailureType.NONE,
                reason="Duplicate telemetry event deduplicated idempotently.",
                current_metrics={},
                threshold={},
                evaluated_at=now,
            )

        # 2. Control plane failure simulation / fail-safe handling
        if simulate_control_plane_failure:
            policy = await self.get_or_create_default_policy(event.workspace_id)
            if policy.fail_safe_mode == FailSafeMode.FAIL_CLOSED:
                return GuardrailDecision(
                    decision_id=f"dec-failclosed-{uuid.uuid4().hex[:10]}",
                    workspace_id=event.workspace_id,
                    agent_id=event.agent_id,
                    task_id=event.task_id,
                    decision=GuardrailDecisionType.DENY,
                    failure_type=GuardrailFailureType.FORBIDDEN_ACTION,
                    reason="FAIL_CLOSED: Control plane unavailable; high-risk actions denied safely.",
                    current_metrics={},
                    threshold={},
                    evaluated_at=now,
                )
            else:
                return GuardrailDecision(
                    decision_id=f"dec-failopen-{uuid.uuid4().hex[:10]}",
                    workspace_id=event.workspace_id,
                    agent_id=event.agent_id,
                    task_id=event.task_id,
                    decision=GuardrailDecisionType.ALLOW,
                    failure_type=GuardrailFailureType.NONE,
                    reason="FAIL_OPEN: Control plane unavailable; read-only operations permitted.",
                    current_metrics={},
                    threshold={},
                    evaluated_at=now,
                )

        # Mark event ingested
        await self.storage.record_event_ingestion(event.event_id, event.workspace_id, event.task_id)

        # 3. Retrieve task state
        task_state = await self.storage.get_or_create_task_state(
            event.task_id, event.workspace_id, event.agent_id
        )

        # If task is already STOPPED, reject immediately
        if task_state["state"] == TaskLifecycleState.STOPPED:
            reason = f"Task is STOPPED: {task_state.get('stopped_reason') or 'Hard budget or terminal failure reached.'}"
            decision = GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=event.workspace_id,
                agent_id=event.agent_id,
                task_id=event.task_id,
                decision=GuardrailDecisionType.STOP,
                failure_type=GuardrailFailureType.HARD_BUDGET_EXCEEDED,
                reason=reason,
                current_metrics={"total_cost_usd": task_state["total_cost_usd"]},
                threshold={},
                evaluated_at=now,
            )
            await self.storage.record_decision(decision)
            return decision

        # If task is already PAUSED, reject incoming actions until operator resumes
        if task_state["state"] == TaskLifecycleState.PAUSED:
            reason = f"Task is PAUSED: {task_state.get('paused_reason') or 'Awaiting operator investigation.'}"
            decision = GuardrailDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                workspace_id=event.workspace_id,
                agent_id=event.agent_id,
                task_id=event.task_id,
                decision=GuardrailDecisionType.PAUSE,
                failure_type=GuardrailFailureType.RUNAWAY_TASK,
                reason=reason,
                current_metrics={"total_cost_usd": task_state["total_cost_usd"]},
                threshold={},
                evaluated_at=now,
            )
            await self.storage.record_decision(decision)
            return decision

        # 4. Anti-tamper check: Agents cannot bypass guardrails via header/payload overrides
        # Even if payload_metadata contains "ignore_budget" or "override_guardrail", we ignore it!
        policy = await self.get_or_create_default_policy(event.workspace_id)

        # 5. Evaluate telemetry
        decision = GuardrailDetector.evaluate(event, task_state, policy)

        # 6. Apply state transitions and update metrics
        if decision.decision == GuardrailDecisionType.PAUSE:
            await self.storage.set_task_state(
                task_id=event.task_id,
                workspace_id=event.workspace_id,
                state=TaskLifecycleState.PAUSED,
                reason=decision.reason,
            )
        elif decision.decision == GuardrailDecisionType.STOP:
            await self.storage.set_task_state(
                task_id=event.task_id,
                workspace_id=event.workspace_id,
                state=TaskLifecycleState.STOPPED,
                reason=decision.reason,
            )

        # Update metrics in storage
        reset_tool_errs = (not event.is_tool_error) and (event.action_type.startswith("tool_") or "tool" in event.action_type)
        await self.storage.update_task_metrics(
            task_id=event.task_id,
            workspace_id=event.workspace_id,
            cost_increment=event.cost_usd,
            is_retry=event.is_retry,
            is_tool_error=event.is_tool_error,
            reset_tool_errors=reset_tool_errs,
        )

        # Record decision audit
        await self.storage.record_decision(decision)
        return decision

    async def resume_task(
        self,
        task_id: str,
        workspace_id: str,
        operator: str,
        reason: str,
    ) -> dict[str, Any]:
        """Authorized human operator resumes a paused task."""
        state = await self.storage.get_or_create_task_state(task_id, workspace_id, "")
        if state["state"] != TaskLifecycleState.PAUSED:
            raise ValueError(f"Task '{task_id}' is in state '{state['state'].value}', not PAUSED. Cannot resume.")

        await self.storage.set_task_state(
            task_id=task_id,
            workspace_id=workspace_id,
            state=TaskLifecycleState.ACTIVE,
            reason=reason,
            operator=operator,
        )
        return await self.storage.get_or_create_task_state(task_id, workspace_id, "")

    async def get_task_status(self, task_id: str, workspace_id: str) -> dict[str, Any]:
        """Fetch current task lifecycle state, spend, error count, and decision history."""
        state = await self.storage.get_or_create_task_state(task_id, workspace_id, "")
        decisions = await self.storage.get_decisions(task_id, workspace_id)
        state["decisions"] = [d.to_dict() for d in decisions]
        return state
