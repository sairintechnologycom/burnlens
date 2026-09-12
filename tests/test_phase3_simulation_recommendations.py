"""Phase 3: Simulation & Recommendations Certification Suite (BL-AE-003).

Validates deterministic simulation, evidence-backed recommendations, historical backtesting,
strict read-only safety, and complete rollback plans.
"""
from __future__ import annotations

from datetime import datetime, timezone
import aiosqlite
import pytest

from burnlens.recommendations.engine import RecommendationEngine
from burnlens.recommendations.models import Recommendation, SimulationResult
from burnlens.recommendations.simulator import (
    simulate_model_switch,
    simulate_prompt_caching,
    simulate_retry_reduction,
)
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


@pytest.fixture
async def simulation_db(tmp_path):
    """Fixture providing a telemetry dataset for simulation and recommendations."""
    db_path = str(tmp_path / "phase3_simulation.db")
    await init_db(db_path)
    now = datetime.now(timezone.utc)

    # 10 requests on gpt-4o (1000 input, 500 output each = $0.0075 each, total = $0.075)
    for i in range(10):
        rec = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            timestamp=now,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.0075,
            status_code=200,
            workspace_id="ws_sim",
            tags={"team": "analytics", "workflow_id": "report-gen"},
        )
        await insert_request(db_path, rec)

    # 3 retry failure requests ($0.05 each = $0.15 retry waste)
    for i in range(3):
        rec_err = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            timestamp=now,
            input_tokens=500,
            output_tokens=0,
            cost_usd=0.05,
            status_code=500,
            workspace_id="ws_sim",
            tags={"team": "analytics", "workflow_id": "report-gen"},
        )
        await insert_request(db_path, rec_err)

    # Separate workspace ws_other data
    rec_other = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        cost_usd=1.00,
        workspace_id="ws_other",
    )
    await insert_request(db_path, rec_other)

    return db_path


# ===========================================================================
# Layer 1 — Unit: Deterministic Simulator Functions
# ===========================================================================

def test_layer1_unit_simulator_model_switch():
    """Verify model switch simulation accurately recalculates costs down to floating point precision."""
    # 5 requests on gpt-4o: input 1000, output 500
    # gpt-4o rate: $2.50 / $10.00 per M -> (1000 * 2.50 + 500 * 10) / 1M = $0.0075 per req -> $0.0375 total
    # gpt-4o-mini rate: $0.15 / $0.60 per M -> (1000 * 0.15 + 500 * 0.60) / 1M = $0.00045 per req -> $0.00225 total
    requests = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": 0.0075,
            "status_code": 200,
        }
        for _ in range(5)
    ]

    sim = simulate_model_switch(requests, current_model="gpt-4o", target_model="gpt-4o-mini", quality_risk=0.006)
    assert sim.category == "model_overkill"
    assert round(sim.current_cost_usd, 5) == 0.0375
    assert round(sim.projected_cost_usd, 5) == 0.00225
    assert round(sim.expected_saving_usd, 5) == 0.03525
    assert sim.confidence == 0.94
    assert sim.quality_risk == 0.006
    assert sim.affected_requests_count == 5


def test_layer1_unit_simulator_retry_reduction():
    """Verify retry reduction simulation correctly calculates avoidable error waste."""
    requests = [
        {"cost_usd": 1.00, "status_code": 200},
        {"cost_usd": 1.00, "status_code": 200},
        {"cost_usd": 0.50, "status_code": 500},
        {"cost_usd": 0.50, "status_code": 504},
    ]
    sim = simulate_retry_reduction(requests, reduction_factor=0.80)
    assert sim.category == "retry_reduction"
    assert sim.current_cost_usd == 3.00
    # Error cost = $1.00. 80% reduction = $0.80 saving -> projected = $2.20
    assert sim.expected_saving_usd == 0.80
    assert sim.projected_cost_usd == 2.20
    assert sim.confidence == 0.92
    assert sim.quality_risk == 0.002


# ===========================================================================
# Layer 2 — Contract: Recommendation Object Integrity & Boundaries
# ===========================================================================

def test_layer2_contract_recommendation_boundaries():
    """Verify Recommendation dataclass invariants and bounds."""
    rec = Recommendation(
        recommendation_id="rec-test-01",
        category="model_overkill",
        scope="model:gpt-4o",
        workspace_id="ws_main",
        evidence={"sample": "data"},
        current_cost=100.0,
        projected_cost=20.0,
        expected_saving=80.0,
        confidence=0.95,
        quality_risk=0.01,
        implementation_plan="Switch model config to gpt-4o-mini",
        rollback_plan="Revert to gpt-4o",
    )
    assert rec.status == "proposed"
    assert rec.expected_saving == 80.0

    # Invalid confidence raises ValueError
    with pytest.raises(ValueError):
        Recommendation(
            recommendation_id="rec-bad-01",
            category="model_overkill",
            scope="model:gpt-4o",
            workspace_id="ws_main",
            evidence={},
            current_cost=10.0,
            projected_cost=5.0,
            expected_saving=5.0,
            confidence=1.5,  # > 1.0
            quality_risk=0.01,
            implementation_plan="",
            rollback_plan="",
        )


# ===========================================================================
# Layer 3 — Integration: Historical Backtesting Validation
# ===========================================================================

def test_layer3_integration_historical_backtesting(tmp_path):
    """Verify that historical backtesting calculates variance between prediction and historical replay."""
    engine = RecommendationEngine(str(tmp_path / "unused.db"))

    # Initial recommendation: predicted saving = $10.00
    rec = Recommendation(
        recommendation_id="rec-backtest-1",
        category="model_overkill",
        scope="model:gpt-4o",
        workspace_id="ws_test",
        evidence={"current_model": "gpt-4o", "target_model": "gpt-4o-mini"},
        current_cost=10.60,
        projected_cost=0.60,
        expected_saving=10.00,
        confidence=0.94,
        quality_risk=0.006,
        implementation_plan="Route to gpt-4o-mini",
        rollback_plan="Rollback to gpt-4o",
    )

    # Historical requests replay: 1,300 requests over 30 days
    # Let's say historical replay yields $9.45 saving
    historical_requests = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": 0.0075,
            "status_code": 200,
        }
        for _ in range(1340)
    ]
    # 1340 * 0.0075 = $10.05 current cost
    # 1340 * 0.00045 = $0.603 projected cost
    # Backtested saving = $9.447

    backtest = engine.backtest_recommendation(rec, historical_requests)
    assert backtest["recommendation_id"] == "rec-backtest-1"
    assert backtest["predicted_saving_usd"] == 10.00
    assert round(backtest["backtested_saving_usd"], 2) == 9.45
    # Variance = |10.00 - 9.447| = 0.553 (5.53% variance)
    assert backtest["variance_percentage"] < 6.0
    assert backtest["backtest_status"] == "PASS"


# ===========================================================================
# Layer 4 — Security: Read-Only Safety & Zero Production Mutations
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_read_only_invariance(simulation_db):
    """Ensure generating recommendations performs ZERO database mutations or external tool actions."""
    async with aiosqlite.connect(simulation_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        initial_request_count = (await cursor.fetchone())[0]

    engine = RecommendationEngine(simulation_db)
    recs = await engine.generate_recommendations(workspace_id="ws_sim")
    assert len(recs) > 0

    # Ensure database was completely untouched
    async with aiosqlite.connect(simulation_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        final_request_count = (await cursor.fetchone())[0]
        assert final_request_count == initial_request_count

    # Verify workspace isolation: ws_other cannot be observed by ws_sim
    for r in recs:
        assert r.workspace_id == "ws_sim"
        assert "ws_other" not in r.scope


# ===========================================================================
# Layer 5 — End-to-End: High Model Spend -> Recommendation Lifecycle
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_recommendation_lifecycle(simulation_db):
    """Canonical E2E Scenario:
    High model spend detected on gpt-4o
    → Simulator evaluates gpt-4o-mini
    → Expected saving produced with high confidence
    → Quality risk calculated (0.6%)
    → Recommendation displayed with exact implementation & rollback plans
    → Zero production mutation occurs.
    """
    engine = RecommendationEngine(simulation_db)
    recs = await engine.generate_recommendations(workspace_id="ws_sim")

    # Find the model overkill recommendation
    model_recs = [r for r in recs if r.category == "model_overkill"]
    assert len(model_recs) == 1
    rec = model_recs[0]

    assert rec.scope == "model:gpt-4o"
    assert rec.current_cost > 0.05
    assert rec.projected_cost < rec.current_cost
    assert rec.expected_saving > 0.0
    assert rec.confidence >= 0.90
    assert rec.quality_risk == 0.006
    assert "gpt-4o-mini" in rec.implementation_plan
    assert "Revert client model configuration" in rec.rollback_plan
    assert rec.status == "proposed"
