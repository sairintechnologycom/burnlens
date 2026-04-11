"""Phase 01: Data Foundation -- Nyquist validation tests.

These tests fill coverage gaps identified during phase validation.
They verify observable behavioral requirements from DATA-01 through DATA-04
that are not covered by the existing test_storage.py suite.
"""
from __future__ import annotations

import json
from datetime import datetime

import aiosqlite
import pytest

from burnlens.storage.database import (
    init_db,
    insert_asset,
    insert_discovery_event,
    insert_provider_signature,
)
from burnlens.storage.models import AiAsset, DiscoveryEvent, ProviderSignature
from burnlens.storage.queries import get_provider_signatures


# ---------------------------------------------------------------------------
# DATA-04: WAL journal mode is enabled after init_db
# ---------------------------------------------------------------------------


async def test_wal_mode_enabled_after_init(tmp_db: str):
    """init_db must set SQLite journal_mode to WAL for concurrent read safety."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
    assert row[0] == "wal", f"Expected WAL journal mode, got {row[0]}"


# ---------------------------------------------------------------------------
# DATA-02: provider_signatures UNIQUE constraint prevents duplicate providers
# ---------------------------------------------------------------------------


async def test_provider_signatures_unique_constraint_rejects_duplicate(tmp_db: str):
    """provider_signatures.provider has a UNIQUE constraint; duplicate inserts are ignored."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        # Attempt to insert a duplicate openai row (should be ignored by INSERT OR IGNORE)
        await db.execute(
            "INSERT OR IGNORE INTO provider_signatures (provider, endpoint_pattern, header_signature, model_field_path) VALUES (?, ?, ?, ?)",
            ("openai", "duplicate.example.com/*", "{}", "body.model"),
        )
        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM provider_signatures WHERE provider = 'openai'")
        row = await cursor.fetchone()
    assert row[0] == 1, "UNIQUE constraint should prevent duplicate provider rows"


# ---------------------------------------------------------------------------
# DATA-02: insert_provider_signature function works correctly
# ---------------------------------------------------------------------------


async def test_insert_provider_signature_returns_id(initialized_db: str):
    """insert_provider_signature should insert a new signature and return a row id."""
    sig = ProviderSignature(
        provider="custom_llm",
        endpoint_pattern="api.customllm.io/*",
        header_signature={"keys": ["x-custom-key"]},
        model_field_path="body.model",
    )
    row_id = await insert_provider_signature(initialized_db, sig)
    assert isinstance(row_id, int)
    assert row_id > 0


async def test_insert_provider_signature_roundtrips_header_signature(initialized_db: str):
    """insert_provider_signature should serialize header_signature as JSON and it should roundtrip."""
    sig = ProviderSignature(
        provider="custom_llm",
        endpoint_pattern="api.customllm.io/*",
        header_signature={"keys": ["x-custom-key", "authorization"]},
        model_field_path="body.custom_model",
    )
    await insert_provider_signature(initialized_db, sig)
    results = await get_provider_signatures(initialized_db, provider="custom_llm")
    assert len(results) == 1
    assert results[0].header_signature == {"keys": ["x-custom-key", "authorization"]}
    assert results[0].model_field_path == "body.custom_model"


# ---------------------------------------------------------------------------
# DATA-02: Bedrock has differentiated model_field_path
# ---------------------------------------------------------------------------


async def test_bedrock_uses_modelId_field_path(initialized_db: str):
    """Bedrock provider signature must use body.modelId, not body.model."""
    results = await get_provider_signatures(initialized_db, provider="bedrock")
    assert len(results) == 1
    assert results[0].model_field_path == "body.modelId", (
        f"Bedrock should use body.modelId, got {results[0].model_field_path}"
    )


# ---------------------------------------------------------------------------
# DATA-01: ai_assets default column values match dataclass defaults
# ---------------------------------------------------------------------------


async def test_ai_asset_defaults_match_database_defaults(initialized_db: str):
    """Inserting an AiAsset with only required fields should produce correct defaults."""
    asset = AiAsset(
        provider="openai",
        model_name="gpt-4o",
        endpoint_url="https://api.openai.com/v1/chat/completions",
    )
    row_id = await insert_asset(initialized_db, asset)
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM ai_assets WHERE id = ?", (row_id,))
        row = await cursor.fetchone()

    assert row["status"] == "shadow", "Default status should be 'shadow'"
    assert row["risk_tier"] == "unclassified", "Default risk_tier should be 'unclassified'"
    assert float(row["monthly_spend_usd"]) == 0.0, "Default monthly_spend_usd should be 0.0"
    assert int(row["monthly_requests"]) == 0, "Default monthly_requests should be 0"
    assert row["api_key_hash"] is None, "Default api_key_hash should be None"
    assert row["owner_team"] is None, "Default owner_team should be None"
    assert row["project"] is None, "Default project should be None"


# ---------------------------------------------------------------------------
# DATA-03: discovery_events empty details default
# ---------------------------------------------------------------------------


async def test_discovery_event_empty_details_roundtrip(initialized_db: str):
    """Inserting a DiscoveryEvent with empty details should store '{}' and roundtrip."""
    event = DiscoveryEvent(event_type="new_asset_detected", details={})
    row_id = await insert_discovery_event(initialized_db, event)

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("SELECT details FROM discovery_events WHERE id = ?", (row_id,))
        row = await cursor.fetchone()

    assert json.loads(row[0]) == {}, "Empty details should roundtrip as {}"


# ---------------------------------------------------------------------------
# DATA-01: ai_assets accepts all valid status enum values
# ---------------------------------------------------------------------------


async def test_ai_assets_accepts_all_valid_status_values(initialized_db: str):
    """All valid status values (active, inactive, shadow, approved, deprecated) should be accepted."""
    valid_statuses = ["active", "inactive", "shadow", "approved", "deprecated"]
    for status in valid_statuses:
        asset = AiAsset(
            provider="openai",
            model_name=f"model-{status}",
            endpoint_url="https://api.openai.com",
            status=status,
        )
        row_id = await insert_asset(initialized_db, asset)
        assert row_id > 0, f"Status '{status}' should be accepted"


# ---------------------------------------------------------------------------
# DATA-01: ai_assets accepts all valid risk_tier enum values
# ---------------------------------------------------------------------------


async def test_ai_assets_accepts_all_valid_risk_tier_values(initialized_db: str):
    """All valid risk_tier values (unclassified, low, medium, high) should be accepted."""
    valid_tiers = ["unclassified", "low", "medium", "high"]
    for tier in valid_tiers:
        asset = AiAsset(
            provider="openai",
            model_name=f"model-{tier}",
            endpoint_url="https://api.openai.com",
            risk_tier=tier,
        )
        row_id = await insert_asset(initialized_db, asset)
        assert row_id > 0, f"Risk tier '{tier}' should be accepted"


# ---------------------------------------------------------------------------
# DATA-03: all 5 discovery event types are accepted by CHECK constraint
# ---------------------------------------------------------------------------


async def test_discovery_events_accepts_all_valid_event_types(initialized_db: str):
    """All 5 event_type values should be accepted by the CHECK constraint."""
    valid_types = [
        "new_asset_detected",
        "model_changed",
        "provider_changed",
        "key_rotated",
        "asset_inactive",
    ]
    for event_type in valid_types:
        event = DiscoveryEvent(event_type=event_type)
        row_id = await insert_discovery_event(initialized_db, event)
        assert row_id > 0, f"Event type '{event_type}' should be accepted"


# ---------------------------------------------------------------------------
# DATA-02: all 7 providers have correct endpoint patterns
# ---------------------------------------------------------------------------


async def test_seeded_provider_endpoint_patterns(initialized_db: str):
    """Each seeded provider should have the correct endpoint wildcard pattern."""
    expected_patterns = {
        "openai": "api.openai.com/*",
        "anthropic": "api.anthropic.com/*",
        "google": "generativelanguage.googleapis.com/*",
        "azure_openai": "*.openai.azure.com/*",
        "bedrock": "bedrock-runtime.*.amazonaws.com/*",
        "cohere": "api.cohere.com/*",
        "mistral": "api.mistral.ai/*",
    }
    results = await get_provider_signatures(initialized_db)
    actual = {s.provider: s.endpoint_pattern for s in results}
    for provider, pattern in expected_patterns.items():
        assert actual.get(provider) == pattern, (
            f"Provider {provider}: expected pattern '{pattern}', got '{actual.get(provider)}'"
        )
