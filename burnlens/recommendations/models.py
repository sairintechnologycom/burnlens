"""Recommendation domain objects for BL-AE-003 Simulation & Recommendations."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


RECOMMENDATION_CATEGORIES = (
    "model_overkill",
    "retry_reduction",
    "context_reduction",
    "caching_opportunity",
    "redundant_tool_calls",
    "runaway_loops",
    "poor_routing",
    "repeated_failures",
)


@dataclass
class SimulationResult:
    """Deterministic result of a simulated configuration or routing optimization."""

    category: str
    current_cost_usd: float
    projected_cost_usd: float
    expected_saving_usd: float
    confidence: float
    quality_risk: float
    affected_requests_count: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recommendation:
    """Actionable optimization recommendation derived from observed evidence and simulation."""

    recommendation_id: str
    category: str
    scope: str
    workspace_id: str
    evidence: dict[str, Any]
    current_cost: float
    projected_cost: float
    expected_saving: float
    confidence: float
    quality_risk: float
    implementation_plan: str
    rollback_plan: str
    status: str = "proposed"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.category not in RECOMMENDATION_CATEGORIES:
            raise ValueError(
                f"Invalid recommendation category: {self.category!r}. "
                f"Expected one of {RECOMMENDATION_CATEGORIES}."
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
        if not (0.0 <= self.quality_risk <= 1.0):
            raise ValueError(f"Quality risk must be between 0.0 and 1.0, got {self.quality_risk}")

    @classmethod
    def generate_id(cls, workspace_id: str, category: str, scope: str) -> str:
        """Create a deterministic unique recommendation id based on scope and category."""
        raw = f"{workspace_id}|{category}|{scope}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
        return f"rec-{category[:6]}-{digest}"
