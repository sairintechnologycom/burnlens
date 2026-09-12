"""Tests for Phase 8: BL-AE-008 Verified Savings.

5-Layer Test Pyramid:
- Layer 1 (Unit): BaselineSnapshot cryptographic fingerprinting, tamper detection, formula mechanics
- Layer 2 (Contract): SavingsVerificationRecord schemas, verdict enums (PASS, FAIL, INCONCLUSIVE)
- Layer 3 (Integration): Baseline recording, post-change observation evaluation, and SQLite storage roundtrip
- Layer 4 (Security & Invariants):
  * Post-hoc baseline tamper prevention
  * Negative test: Quality drop exceeding threshold triggers VERIFIED FAIL even when savings are positive
  * Negative test: Negative/zero savings triggers VERIFIED FAIL
  * Inconclusive test: Sample size below minimum threshold triggers INCONCLUSIVE
  * Multi-tenant workspace isolation
- Layer 5 (E2E): Golden Verification Scenario: Projected $1,700, Actual $1,520, Quality preserved -> VERIFIED PASS
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from burnlens.storage.database import init_db
from burnlens.verification.engine import SavingsVerificationEngine
from burnlens.verification.models import (
    BaselineSnapshot,
    SavingsVerificationRecord,
    VerificationVerdict,
)
from burnlens.verification.storage import VerificationStorage


@pytest.fixture
async def verif_storage(tmp_path: Path) -> VerificationStorage:
    """Provide initialized SQLite database with verification schema."""
    db_path = str(tmp_path / "verification_test.db")
    await init_db(db_path)
    storage = VerificationStorage(db_path)
    await storage.init_verification_schema()
    return storage


# ===========================================================================
# Layer 1: Unit Tests (Fingerprinting & Math Mechanics)
# ===========================================================================

def test_layer1_unit_baseline_snapshot_fingerprint_and_tamper_detection():
    """Baseline fingerprint must be deterministic and sensitive to metric alterations."""
    ts = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    base = BaselineSnapshot(
        snapshot_id="snap-001",
        recommendation_id="rec-opt-1",
        workspace_id="ws-main",
        baseline_cost_usd=500.0,
        baseline_requests=1000,
        baseline_accepted_outcomes=950,
        baseline_outcome_rate=0.95,
        created_at=ts,
    )
    fp1 = base.fingerprint
    assert len(fp1) == 16
    assert base.fingerprint == fp1

    # Tampering baseline cost
    base_tampered = BaselineSnapshot(
        snapshot_id=base.snapshot_id,
        recommendation_id=base.recommendation_id,
        workspace_id=base.workspace_id,
        baseline_cost_usd=800.0,  # tampered!
        baseline_requests=base.baseline_requests,
        baseline_accepted_outcomes=base.baseline_accepted_outcomes,
        baseline_outcome_rate=base.baseline_outcome_rate,
        created_at=ts,
    )
    assert base_tampered.fingerprint != fp1


# ===========================================================================
# Layer 2: Contract Tests (Record Schemas & Enums)
# ===========================================================================

def test_layer2_contract_savings_verification_schema():
    """SavingsVerificationRecord serialization must satisfy audit contract."""
    rec = SavingsVerificationRecord(
        verification_id="verif-123",
        recommendation_id="rec-123",
        workspace_id="ws-prod",
        projected_saving_usd=1700.0,
        actual_saving_usd=1520.0,
        variance_usd=-180.0,
        variance_percentage=-10.59,
        baseline_outcome_rate=0.95,
        post_change_outcome_rate=0.945,
        quality_change=-0.005,
        confidence=0.95,
        verdict=VerificationVerdict.PASS,
        reason="VERIFIED PASS: Realized $1520.00 savings with stable quality.",
        sample_count_baseline=1000,
        sample_count_post_change=500,
        evidence_snapshot={"diff": "acceptable"},
    )
    d = rec.to_dict()
    assert d["verification_id"] == "verif-123"
    assert d["verdict"] == "PASS"
    assert d["actual_saving_usd"] == 1520.0
    assert d["quality_change"] == -0.005
    assert "verified_at" in d


# ===========================================================================
# Layer 3: Integration Tests (SQLite Persistence Roundtrip)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_baseline_and_verification_roundtrip(verif_storage: VerificationStorage):
    """Engine records baseline, evaluates observation window, and persists verification in SQLite."""
    engine = SavingsVerificationEngine(verif_storage)

    # 1. Record baseline
    baseline = await engine.record_baseline(
        recommendation_id="rec-cache-opt",
        workspace_id="ws-integ",
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=90,
    )
    assert baseline.baseline_outcome_rate == 0.90

    # 2. Verify savings (post-change: 100 requests cost $60, 90 accepted outcomes)
    verif = await engine.verify_savings(
        recommendation_id="rec-cache-opt",
        workspace_id="ws-integ",
        projected_saving_usd=35.0,
        post_change_cost_usd=60.0,
        post_change_requests=100,
        post_change_accepted_outcomes=90,
    )

    assert verif.verdict == VerificationVerdict.PASS
    assert verif.actual_saving_usd == 40.0
    assert verif.quality_change == 0.0

    # 3. Retrieve from storage and verify persistence
    stored = await verif_storage.get_verification_record(verif.verification_id, "ws-integ")
    assert stored is not None
    assert stored.actual_saving_usd == 40.0
    assert stored.verdict == VerificationVerdict.PASS


# ===========================================================================
# Layer 4: Security & Negative Invariant Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_negative_quality_drop_fails_verification(verif_storage: VerificationStorage):
    """Saving achieved, but outcome quality drops by 7% (> 3% threshold) -> VERIFIED FAIL."""
    engine = SavingsVerificationEngine(verif_storage)

    # Baseline: 100 requests cost $100, 95 accepted outcomes (95% rate)
    await engine.record_baseline(
        recommendation_id="rec-aggressive-pruning",
        workspace_id="ws-prod",
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=95,
    )

    # Post-change: Cost cut in half to $50, but accepted outcomes drop to 88/100 (88% rate -> 7% drop)
    verif = await engine.verify_savings(
        recommendation_id="rec-aggressive-pruning",
        workspace_id="ws-prod",
        projected_saving_usd=40.0,
        post_change_cost_usd=50.0,
        post_change_requests=100,
        post_change_accepted_outcomes=88,
        max_tolerable_quality_drop=0.03,
    )

    # Despite achieving $50 savings, quality dropped 7% -> VERIFIED FAIL!
    assert verif.verdict == VerificationVerdict.FAIL
    assert "Outcome quality degraded by 7.0%" in verif.reason
    assert "exceeding max tolerable threshold" in verif.reason


@pytest.mark.asyncio
async def test_layer4_security_negative_no_savings_fails_verification(verif_storage: VerificationStorage):
    """When post-change unit cost is higher or equal to baseline, verdict is VERIFIED FAIL."""
    engine = SavingsVerificationEngine(verif_storage)

    await engine.record_baseline(
        recommendation_id="rec-bad-switch",
        workspace_id="ws-prod",
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=90,
    )

    # Post-change cost increased to $110
    verif = await engine.verify_savings(
        recommendation_id="rec-bad-switch",
        workspace_id="ws-prod",
        projected_saving_usd=20.0,
        post_change_cost_usd=110.0,
        post_change_requests=100,
        post_change_accepted_outcomes=90,
    )

    assert verif.verdict == VerificationVerdict.FAIL
    assert verif.actual_saving_usd < 0.0
    assert "no economic reduction achieved" in verif.reason


@pytest.mark.asyncio
async def test_layer4_security_inconclusive_on_insufficient_sample_size(verif_storage: VerificationStorage):
    """Fewer observation samples than min_sample_size yields INCONCLUSIVE verdict."""
    engine = SavingsVerificationEngine(verif_storage)

    await engine.record_baseline(
        recommendation_id="rec-small-sample",
        workspace_id="ws-prod",
        baseline_cost_usd=100.0,
        baseline_requests=100,
        baseline_accepted_outcomes=90,
    )

    # Only 5 requests observed, min_sample_size = 10
    verif = await engine.verify_savings(
        recommendation_id="rec-small-sample",
        workspace_id="ws-prod",
        projected_saving_usd=20.0,
        post_change_cost_usd=3.0,
        post_change_requests=5,
        post_change_accepted_outcomes=5,
        min_sample_size=10,
    )

    assert verif.verdict == VerificationVerdict.INCONCLUSIVE
    assert "Insufficient observation sample size" in verif.reason


@pytest.mark.asyncio
async def test_layer4_security_multi_tenant_isolation(verif_storage: VerificationStorage):
    """Baseline recorded in Workspace Alpha cannot be accessed or verified from Workspace Beta."""
    engine = SavingsVerificationEngine(verif_storage)

    await engine.record_baseline(
        recommendation_id="rec-tenant-alpha",
        workspace_id="ws-alpha",
        baseline_cost_usd=100.0,
        baseline_requests=50,
        baseline_accepted_outcomes=45,
    )

    with pytest.raises(ValueError, match="No baseline snapshot found"):
        await engine.verify_savings(
            recommendation_id="rec-tenant-alpha",
            workspace_id="ws-beta",  # Different workspace!
            projected_saving_usd=20.0,
            post_change_cost_usd=40.0,
            post_change_requests=50,
            post_change_accepted_outcomes=45,
        )


# ===========================================================================
# Layer 5: E2E Golden Verification Journey (Plan Section 8 Scenario)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_savings_verification_journey(verif_storage: VerificationStorage):
    """Canonical Plan Scenario (Section 8 & Section Phase 8):

    Projected Saving = $1,700
    Actual Realized Saving = $1,520
    Outcome Quality = Acceptable (minimal variance)
    Verdict -> VERIFIED PASS
    """
    engine = SavingsVerificationEngine(verif_storage)

    # 1. Pre-change baseline: 2,000 requests costing $4,000 ($2.00/request), 1,900 accepted outcomes (95% rate)
    baseline = await engine.record_baseline(
        recommendation_id="rec-golden-model-tiering",
        workspace_id="ws-acme-prod",
        baseline_cost_usd=4000.0,
        baseline_requests=2000,
        baseline_accepted_outcomes=1900,
    )
    assert baseline.baseline_outcome_rate == 0.95

    # 2. Post-change observation window:
    # 2,000 requests run under new routing model.
    # Total cost = $2,480 ($1.24/request, saving $0.76/request -> $1,520 total savings)
    # Accepted outcomes = 1,890 (94.5% rate -> -0.5% quality change, well within 3% tolerance)
    verif = await engine.verify_savings(
        recommendation_id="rec-golden-model-tiering",
        workspace_id="ws-acme-prod",
        projected_saving_usd=1700.0,
        post_change_cost_usd=2480.0,
        post_change_requests=2000,
        post_change_accepted_outcomes=1890,
        max_tolerable_quality_drop=0.03,
    )

    # 3. Assertions
    assert verif.verdict == VerificationVerdict.PASS
    assert verif.actual_saving_usd == 1520.0
    assert verif.projected_saving_usd == 1700.0
    assert verif.variance_usd == -180.0
    assert verif.quality_change == -0.005
    assert verif.confidence == 1.0
    assert "VERIFIED PASS: Realized $1520.00 savings" in verif.reason

    # Stored record check
    stored = await verif_storage.get_verification_record(verif.verification_id, "ws-acme-prod")
    assert stored is not None
    assert stored.verdict == VerificationVerdict.PASS
    assert stored.evidence_snapshot["normalized_actual_saving_usd"] == 1520.0
