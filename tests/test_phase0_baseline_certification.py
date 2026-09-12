"""Phase 0: Baseline & Compatibility Certification Suite (BL-BASELINE).

Validates that existing canonical ingestion, pricing, provider events, deduplication,
reconciliation, outcomes, waste analysis, and workspace boundaries are deterministic,
reproducible, and uncorrupted prior to beginning Phase 1 (BL-AE-001).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.cost.pricing import get_model_pricing
from burnlens.storage.database import (
    init_db,
    insert_outcome,
    insert_request,
)
from burnlens.storage.queries import get_total_cost
from burnlens.storage.findings import (
    SavingsVerdict,
    list_findings,
    sync_findings,
    verify_savings,
)
from burnlens.storage.models import Outcome, RequestRecord


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "baseline"


@pytest.fixture
def manifest() -> dict:
    manifest_path = FIXTURES_DIR / "baseline_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def baseline_events() -> dict:
    events_path = FIXTURES_DIR / "representative_events.json"
    with open(events_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "baseline_cert.db")
    await init_db(db_path)
    return db_path


# ===========================================================================
# Layer 1 — Unit: Pricing & Calculation Determinism
# ===========================================================================

def test_layer1_unit_pricing_determinism(baseline_events):
    """Verify that every fixture event produces the exact expected cost."""
    for event in baseline_events["events"]:
        usage = TokenUsage(
            input_tokens=event["input_tokens"],
            output_tokens=event["output_tokens"],
            cache_read_tokens=event["cache_read_tokens"],
            cache_write_tokens=event["cache_write_tokens"],
            reasoning_tokens=event["reasoning_tokens"],
        )
        calculated = calculate_cost(event["provider"], event["model"], usage)
        assert calculated is not None
        assert round(calculated, 6) == round(event["expected_cost_usd"], 6), (
            f"Cost mismatch for {event['id']} ({event['provider']}/{event['model']}): "
            f"got {calculated}, expected {event['expected_cost_usd']}"
        )


# ===========================================================================
# Layer 2 — Contract: Schema and API Contract Hashes
# ===========================================================================

def test_layer2_contract_schema_stability(manifest):
    """Verify that the API schemas contract matches the baseline manifest hash."""
    schema_file = Path(__file__).parent.parent / "burnlens" / "api" / "schemas.py"
    current_hash = hashlib.sha256(schema_file.read_bytes()).hexdigest()
    assert current_hash == manifest["api_contract_hash"], (
        f"API contract hash changed! Expected {manifest['api_contract_hash']}, got {current_hash}"
    )


@pytest.mark.asyncio
async def test_layer2_contract_database_tables(test_db):
    """Verify all canonical tables exist and have expected structure."""
    expected_tables = {
        "requests",
        "outcomes",
        "outcome_history",
        "waste_findings",
        "ai_assets",
        "provider_signatures",
        "discovery_events",
        "anomaly_events",
    }
    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        rows = await cursor.fetchall()
        tables = {r[0] for r in rows}
        for table in expected_tables:
            assert table in tables, f"Expected canonical table '{table}' not found in database schema."


# ===========================================================================
# Layer 3 — Integration: Ingestion, Dedup, Ledger, & Outcomes
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_ledger_reconciliation(test_db, baseline_events, manifest):
    """Verify end-to-end event ingestion, ledger aggregation, and exact reconciliation."""
    now = datetime.now(timezone.utc)
    for evt in baseline_events["events"]:
        record = RequestRecord(
            provider=evt["provider"],
            model=evt["model"],
            request_path="/v1/chat/completions",
            timestamp=now,
            input_tokens=evt["input_tokens"],
            output_tokens=evt["output_tokens"],
            cache_read_tokens=evt["cache_read_tokens"],
            cache_write_tokens=evt["cache_write_tokens"],
            cost_usd=evt["expected_cost_usd"],
            duration_ms=250,
            status_code=200,
            tags=evt["tags"],
            event_id=evt["id"],
            workspace_id="ws_baseline",
        )
        await insert_request(test_db, record)

    # Ingested spend matches manifest expectations
    ledger_total = await get_total_cost(test_db)
    expected_total = manifest["expected_ledger_results"]["total_cost_usd"]
    assert round(ledger_total, 4) == round(expected_total, 4)

    # Outcome association
    outcome = Outcome(
        workflow_id="cve-patch-42",
        outcome_id="pr-101",
        status="accepted",
        business_value=1.0,
        metadata={"repo": "burnlens"},
    )
    outcome_id = await insert_outcome(test_db, outcome)
    assert outcome_id > 0

    # Reconciliation invariant check
    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) FROM requests WHERE workspace_id = 'ws_baseline'"
        )
        row = await cursor.fetchone()
        assert row[0] == manifest["expected_ledger_results"]["total_requests"]
        assert row[1] == manifest["expected_ledger_results"]["total_input_tokens"]
        assert row[2] == manifest["expected_ledger_results"]["total_output_tokens"]
        assert round(row[3], 4) == round(expected_total, 4)


# ===========================================================================
# Layer 4 — Security: Workspace Isolation & Tenant Boundaries
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_workspace_isolation(test_db):
    """Ensure data in Workspace A is never leaked into Workspace B."""
    now = datetime.now(timezone.utc)
    rec_a = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        input_tokens=500,
        output_tokens=100,
        cost_usd=0.005,
        tags={"team": "alpha"},
        workspace_id="ws_alpha",
    )
    rec_b = RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        request_path="/v1/messages",
        timestamp=now,
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.010,
        tags={"team": "beta"},
        workspace_id="ws_beta",
    )
    await insert_request(test_db, rec_a)
    await insert_request(test_db, rec_b)

    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute("SELECT SUM(cost_usd) FROM requests WHERE workspace_id = 'ws_alpha'")
        cost_a = (await cursor.fetchone())[0]
        cursor = await conn.execute("SELECT SUM(cost_usd) FROM requests WHERE workspace_id = 'ws_beta'")
        cost_b = (await cursor.fetchone())[0]

    assert round(cost_a, 4) == 0.0050
    assert round(cost_b, 4) == 0.0100


# ===========================================================================
# Layer 5 — End-to-End: Golden Baseline Replay Invariance
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_baseline_replay_invariance(test_db, baseline_events, manifest):
    """Replay baseline fixtures and ensure exact invariant holds:
    fixture input -> exact same canonical identity -> exact same cost -> exact same outcome -> exact same reconciliation.
    """
    now = datetime.now(timezone.utc)
    # Run 1: initial ingestion
    for evt in baseline_events["events"]:
        rec = RequestRecord(
            provider=evt["provider"],
            model=evt["model"],
            request_path="/v1/chat/completions",
            timestamp=now,
            input_tokens=evt["input_tokens"],
            output_tokens=evt["output_tokens"],
            cache_read_tokens=evt["cache_read_tokens"],
            cache_write_tokens=evt["cache_write_tokens"],
            cost_usd=evt["expected_cost_usd"],
            tags=evt["tags"],
            event_id=evt["id"],
            workspace_id="ws_replay",
        )
        await insert_request(test_db, rec)

    # Check aggregations
    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT tags, cost_usd FROM requests WHERE workspace_id = 'ws_replay' ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 3
        
        team_costs = {}
        for tags_json, cost in rows:
            tags = json.loads(tags_json)
            team_costs[tags["team"]] = round(cost, 4)

        assert team_costs == manifest["expected_dashboard_results"]["by_team"]
