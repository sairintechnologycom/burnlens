"""Phase 8: BL-AE-008 Verified Savings Data Models.

Defines:
- VerificationVerdict: PASS, FAIL, INCONCLUSIVE
- BaselineSnapshot: Immutable cryptographic snapshot of pre-change metrics
- SavingsVerificationRecord: Comprehensive outcome & savings verification record
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class VerificationVerdict(str, Enum):
    """Result of savings & quality verification."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class BaselineSnapshot:
    """Immutable pre-change baseline economics and outcome quality snapshot."""

    snapshot_id: str
    recommendation_id: str
    workspace_id: str
    baseline_cost_usd: float
    baseline_requests: int
    baseline_accepted_outcomes: int
    baseline_outcome_rate: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint preventing post-hoc baseline tampering."""
        raw = (
            f"{self.snapshot_id}:{self.recommendation_id}:{self.workspace_id}:"
            f"{self.baseline_cost_usd:.4f}:{self.baseline_requests}:"
            f"{self.baseline_accepted_outcomes}:{self.baseline_outcome_rate:.4f}:"
            f"{self.created_at.isoformat()}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class SavingsVerificationRecord:
    """Formal audit record comparing projected vs actual economics and quality."""

    verification_id: str
    recommendation_id: str
    workspace_id: str
    projected_saving_usd: float
    actual_saving_usd: float
    variance_usd: float
    variance_percentage: float
    baseline_outcome_rate: float
    post_change_outcome_rate: float
    quality_change: float
    confidence: float
    verdict: VerificationVerdict
    reason: str
    sample_count_baseline: int
    sample_count_post_change: int
    evidence_snapshot: dict[str, Any]
    max_tolerable_quality_drop: float = 0.03
    calculation_version: int = 1
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "recommendation_id": self.recommendation_id,
            "workspace_id": self.workspace_id,
            "projected_saving_usd": self.projected_saving_usd,
            "actual_saving_usd": self.actual_saving_usd,
            "variance_usd": self.variance_usd,
            "variance_percentage": self.variance_percentage,
            "baseline_outcome_rate": self.baseline_outcome_rate,
            "post_change_outcome_rate": self.post_change_outcome_rate,
            "quality_change": self.quality_change,
            "confidence": self.confidence,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "sample_count_baseline": self.sample_count_baseline,
            "sample_count_post_change": self.sample_count_post_change,
            "evidence_snapshot": self.evidence_snapshot,
            "max_tolerable_quality_drop": self.max_tolerable_quality_drop,
            "calculation_version": self.calculation_version,
            "verified_at": self.verified_at.isoformat(),
        }
