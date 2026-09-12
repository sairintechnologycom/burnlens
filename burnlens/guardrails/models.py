"""Phase 7: BL-AE-007 Runtime Guardrails Data Models.

Defines:
- GuardrailDecisionType: ALLOW, PAUSE, STOP, DENY
- GuardrailFailureType: RETRY_STORM, HARD_BUDGET_EXCEEDED, RUNAWAY_TASK, REPEATED_TOOL_ERROR, FORBIDDEN_ACTION
- TaskLifecycleState: ACTIVE, PAUSED, STOPPED, COMPLETED
- FailSafeMode: FAIL_OPEN, FAIL_CLOSED
- GuardrailPolicy: Versioned, workspace-scoped operational boundaries
- GuardrailDecision: Immutable decision record with deterministic justification and metric evidence
- RuntimeTelemetryEvent: Granular runtime telemetry ingested for guardrail evaluation
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class GuardrailDecisionType(str, Enum):
    """Actions produced by runtime guardrail evaluation."""

    ALLOW = "ALLOW"
    PAUSE = "PAUSE"
    STOP = "STOP"
    DENY = "DENY"


class GuardrailFailureType(str, Enum):
    """Categorized runtime/economic failure conditions."""

    NONE = "none"
    RETRY_STORM = "retry_storm"
    HARD_BUDGET_EXCEEDED = "hard_budget_exceeded"
    RUNAWAY_TASK = "runaway_task"
    REPEATED_TOOL_ERROR = "repeated_tool_error"
    FORBIDDEN_ACTION = "forbidden_action"


class TaskLifecycleState(str, Enum):
    """Lifecycle state of an agentic task under guardrail supervision."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


class FailSafeMode(str, Enum):
    """Fail-safe behavior when the control plane encounters internal failures or timeouts."""

    FAIL_OPEN = "FAIL_OPEN"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass
class GuardrailPolicy:
    """Workspace-scoped operational constraints for agents and tasks."""

    policy_id: str
    workspace_id: str
    name: str = "Default Runtime Guardrails"
    max_retries: int = 3
    hard_budget_usd: float = 25.0
    max_consecutive_tool_errors: int = 3
    max_task_requests: int = 50
    forbidden_actions: list[str] = field(default_factory=lambda: [
        "change_iam",
        "drop_database",
        "direct_push_main",
        "auto_merge",
    ])
    fail_safe_mode: FailSafeMode = FailSafeMode.FAIL_CLOSED
    version: int = 1
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Deterministic hash of policy parameters."""
        raw = (
            f"{self.policy_id}:{self.workspace_id}:{self.max_retries}:{self.hard_budget_usd}:"
            f"{self.max_consecutive_tool_errors}:{self.max_task_requests}:{','.join(sorted(self.forbidden_actions))}:"
            f"{self.fail_safe_mode.value}:{self.version}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class RuntimeTelemetryEvent:
    """Incoming runtime telemetry unit from an agent execution step."""

    event_id: str
    workspace_id: str
    agent_id: str
    task_id: str
    action_type: str
    cost_usd: float = 0.0
    is_retry: bool = False
    is_tool_error: bool = False
    target_resource: str = ""
    payload_metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GuardrailDecision:
    """Deterministic, explainable decision resulting from runtime guardrail evaluation."""

    decision_id: str
    workspace_id: str
    agent_id: str
    task_id: str
    decision: GuardrailDecisionType
    failure_type: GuardrailFailureType
    reason: str
    current_metrics: dict[str, Any]
    threshold: dict[str, Any]
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "decision": self.decision.value,
            "failure_type": self.failure_type.value,
            "reason": self.reason,
            "current_metrics": self.current_metrics,
            "threshold": self.threshold,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
