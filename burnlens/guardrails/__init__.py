"""Phase 7: BL-AE-007 Runtime Guardrails.

Provides deterministic, explainable runtime supervision for AI agents.
Detects retry storms, runaway task loops, repeated tool errors, hard budget exhaustion,
and unauthorized actions, with reversible human operator pause/resume controls.
"""
from __future__ import annotations

from burnlens.guardrails.detector import GuardrailDetector
from burnlens.guardrails.engine import GuardrailEngine
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

__all__ = [
    "FailSafeMode",
    "GuardrailDecision",
    "GuardrailDecisionType",
    "GuardrailDetector",
    "GuardrailEngine",
    "GuardrailFailureType",
    "GuardrailPolicy",
    "GuardrailStorage",
    "RuntimeTelemetryEvent",
    "TaskLifecycleState",
]
