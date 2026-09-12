"""Phase 8: BL-AE-008 Verified Savings Engine.

Deterministic, evidence-grounded engine for proving optimization value:
- Establishes immutable baseline snapshots
- Measures post-change actual savings vs projected savings
- Detects outcome quality degradation
- Produces unambiguous PASS / FAIL / INCONCLUSIVE verdicts
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from burnlens.verification.models import (
    BaselineSnapshot,
    SavingsVerificationRecord,
    VerificationVerdict,
)
from burnlens.verification.storage import VerificationStorage

logger = logging.getLogger(__name__)


class SavingsVerificationEngine:
    """Calculates and certifies verified savings against immutable baselines."""

    def __init__(self, storage: VerificationStorage) -> None:
        self.storage = storage

    async def record_baseline(
        self,
        recommendation_id: str,
        workspace_id: str,
        baseline_cost_usd: float,
        baseline_requests: int,
        baseline_accepted_outcomes: int,
    ) -> BaselineSnapshot:
        """Create and cryptographically fingerprint a pre-change baseline snapshot."""
        if baseline_requests <= 0:
            raise ValueError(f"baseline_requests must be > 0, got {baseline_requests}")

        outcome_rate = round(baseline_accepted_outcomes / baseline_requests, 4)
        snapshot = BaselineSnapshot(
            snapshot_id=f"snap-{uuid.uuid4().hex[:12]}",
            recommendation_id=recommendation_id,
            workspace_id=workspace_id,
            baseline_cost_usd=round(baseline_cost_usd, 4),
            baseline_requests=baseline_requests,
            baseline_accepted_outcomes=baseline_accepted_outcomes,
            baseline_outcome_rate=outcome_rate,
        )
        await self.storage.save_baseline_snapshot(snapshot)
        return snapshot

    async def verify_savings(
        self,
        recommendation_id: str,
        workspace_id: str,
        projected_saving_usd: float,
        post_change_cost_usd: float,
        post_change_requests: int,
        post_change_accepted_outcomes: int,
        min_sample_size: int = 10,
        max_tolerable_quality_drop: float = 0.03,
    ) -> SavingsVerificationRecord:
        """Evaluate post-change observation window against pre-change baseline.

        Verdict Invariants:
        - If post_change_requests < min_sample_size -> INCONCLUSIVE
        - If quality drop > max_tolerable_quality_drop (e.g. > 3%) -> FAIL (even if cost dropped)
        - If actual_saving_usd <= 0.0 -> FAIL
        - If savings achieved AND quality drop <= max_tolerable_quality_drop -> PASS
        """
        now = datetime.now(timezone.utc)
        baseline = await self.storage.get_baseline_snapshot(recommendation_id, workspace_id)
        if baseline is None:
            raise ValueError(
                f"No baseline snapshot found for recommendation '{recommendation_id}' in workspace '{workspace_id}'"
            )

        verification_id = f"verif-{uuid.uuid4().hex[:12]}"

        # Check sample size
        if post_change_requests < min_sample_size:
            rec = SavingsVerificationRecord(
                verification_id=verification_id,
                recommendation_id=recommendation_id,
                workspace_id=workspace_id,
                projected_saving_usd=projected_saving_usd,
                actual_saving_usd=0.0,
                variance_usd=-projected_saving_usd,
                variance_percentage=-100.0,
                baseline_outcome_rate=baseline.baseline_outcome_rate,
                post_change_outcome_rate=0.0,
                quality_change=0.0,
                confidence=round(post_change_requests / float(min_sample_size), 2),
                verdict=VerificationVerdict.INCONCLUSIVE,
                reason=f"Insufficient observation sample size: {post_change_requests} requests observed (minimum required: {min_sample_size}).",
                sample_count_baseline=baseline.baseline_requests,
                sample_count_post_change=post_change_requests,
                evidence_snapshot={
                    "baseline": {
                        "cost": baseline.baseline_cost_usd,
                        "requests": baseline.baseline_requests,
                        "outcomes": baseline.baseline_accepted_outcomes,
                    },
                    "post_change": {
                        "cost": post_change_cost_usd,
                        "requests": post_change_requests,
                        "outcomes": post_change_accepted_outcomes,
                    },
                },
                max_tolerable_quality_drop=max_tolerable_quality_drop,
                verified_at=now,
            )
            await self.storage.save_verification_record(rec)
            return rec

        # Compute normalized unit costs
        base_unit_cost = baseline.baseline_cost_usd / baseline.baseline_requests
        post_unit_cost = post_change_cost_usd / post_change_requests
        actual_unit_saving = base_unit_cost - post_unit_cost
        actual_saving_usd = round(actual_unit_saving * post_change_requests, 4)

        variance_usd = round(actual_saving_usd - projected_saving_usd, 4)
        variance_pct = round((variance_usd / max(0.001, projected_saving_usd)) * 100.0, 2)

        # Outcome quality rate
        post_outcome_rate = round(post_change_accepted_outcomes / post_change_requests, 4)
        quality_change = round(post_outcome_rate - baseline.baseline_outcome_rate, 4)

        # Confidence bounded by observation depth
        confidence = round(min(1.0, post_change_requests / 50.0), 2)

        # Verdict logic
        evidence_data = {
            "baseline": {
                "unit_cost_usd": round(base_unit_cost, 6),
                "total_cost_usd": baseline.baseline_cost_usd,
                "requests": baseline.baseline_requests,
                "outcome_rate": baseline.baseline_outcome_rate,
                "fingerprint": baseline.fingerprint,
            },
            "post_change": {
                "unit_cost_usd": round(post_unit_cost, 6),
                "total_cost_usd": post_change_cost_usd,
                "requests": post_change_requests,
                "outcome_rate": post_outcome_rate,
            },
            "normalized_actual_saving_usd": actual_saving_usd,
            "projected_saving_usd": projected_saving_usd,
            "variance_usd": variance_usd,
            "quality_change": quality_change,
        }

        # Quality check first: If quality degraded beyond tolerance threshold
        if quality_change < -max_tolerable_quality_drop:
            drop_pct = abs(quality_change) * 100.0
            tol_pct = max_tolerable_quality_drop * 100.0
            verdict = VerificationVerdict.FAIL
            reason = (
                f"VERIFIED FAIL: Outcome quality degraded by {drop_pct:.1f}%, "
                f"exceeding max tolerable threshold of {tol_pct:.1f}%."
            )
        elif actual_saving_usd <= 0.0:
            verdict = VerificationVerdict.FAIL
            reason = (
                f"VERIFIED FAIL: Actual saving was ${actual_saving_usd:.2f}; "
                f"no economic reduction achieved relative to baseline."
            )
        else:
            verdict = VerificationVerdict.PASS
            reason = (
                f"VERIFIED PASS: Realized ${actual_saving_usd:.2f} savings "
                f"(projected: ${projected_saving_usd:.2f}) with stable outcome quality "
                f"({quality_change:+.2%})."
            )

        record = SavingsVerificationRecord(
            verification_id=verification_id,
            recommendation_id=recommendation_id,
            workspace_id=workspace_id,
            projected_saving_usd=projected_saving_usd,
            actual_saving_usd=actual_saving_usd,
            variance_usd=variance_usd,
            variance_percentage=variance_pct,
            baseline_outcome_rate=baseline.baseline_outcome_rate,
            post_change_outcome_rate=post_outcome_rate,
            quality_change=quality_change,
            confidence=confidence,
            verdict=verdict,
            reason=reason,
            sample_count_baseline=baseline.baseline_requests,
            sample_count_post_change=post_change_requests,
            evidence_snapshot=evidence_data,
            max_tolerable_quality_drop=max_tolerable_quality_drop,
            verified_at=now,
        )
        await self.storage.save_verification_record(record)
        return record
