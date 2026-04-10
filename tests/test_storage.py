"""Tests for SQLite database layer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.storage.queries import (
    get_daily_cost,
    get_recent_requests,
    get_requests_for_analysis,
    get_total_cost,
    get_total_request_count,
    get_usage_by_model,
    get_usage_by_tag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    provider: str = "openai",
    model: str = "gpt-4o",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.01,
    tags: dict | None = None,
    system_prompt_hash: str | None = None,
    timestamp: datetime | None = None,
) -> RequestRecord:
    r = RequestRecord(
        provider=provider,
        model=model,
        request_path="/v1/chat/completions",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        tags=tags or {},
        system_prompt_hash=system_prompt_hash,
    )
    if timestamp is not None:
        r.timestamp = timestamp
    return r


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


async def test_init_creates_tables(initialized_db: str):
    """init_db should be idempotent and create the requests table."""
    # Second call should not fail (CREATE TABLE IF NOT EXISTS)
    await init_db(initialized_db)


async def test_init_creates_requests_table(tmp_db: str):
    """Fresh DB should have a requests table after init."""
    await init_db(tmp_db)
    import aiosqlite

    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='requests'"
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "requests"


async def test_init_creates_indexes(tmp_db: str):
    await init_db(tmp_db)
    import aiosqlite

    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        rows = await cursor.fetchall()
    index_names = {r[0] for r in rows}
    assert "idx_requests_timestamp" in index_names
    assert "idx_requests_model" in index_names


# ---------------------------------------------------------------------------
# insert_request
# ---------------------------------------------------------------------------


async def test_insert_and_retrieve(initialized_db: str):
    record = _record()
    row_id = await insert_request(initialized_db, record)
    assert isinstance(row_id, int)
    assert row_id > 0

    rows = await get_recent_requests(initialized_db, limit=10)
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["provider"] == "openai"


async def test_insert_returns_incrementing_ids(initialized_db: str):
    id1 = await insert_request(initialized_db, _record())
    id2 = await insert_request(initialized_db, _record())
    assert id2 > id1


async def test_insert_all_token_fields(initialized_db: str):
    record = RequestRecord(
        provider="openai",
        model="o1",
        request_path="/v1/chat/completions",
        input_tokens=1000,
        output_tokens=500,
        reasoning_tokens=200,
        cache_read_tokens=300,
        cache_write_tokens=0,
        cost_usd=0.05,
        duration_ms=1234,
        status_code=200,
    )
    await insert_request(initialized_db, record)
    rows = await get_recent_requests(initialized_db)
    assert rows[0]["reasoning_tokens"] == 200
    assert rows[0]["cache_read_tokens"] == 300
    assert rows[0]["duration_ms"] == 1234


async def test_tags_roundtrip(initialized_db: str):
    record = _record(tags={"team": "ml", "env": "prod"})
    await insert_request(initialized_db, record)
    rows = await get_recent_requests(initialized_db)
    assert rows[0]["tags"] == {"team": "ml", "env": "prod"}


async def test_empty_tags_roundtrip(initialized_db: str):
    await insert_request(initialized_db, _record(tags={}))
    rows = await get_recent_requests(initialized_db)
    assert rows[0]["tags"] == {}


async def test_system_prompt_hash_persisted(initialized_db: str):
    record = _record(system_prompt_hash="abc123def456")
    await insert_request(initialized_db, record)
    rows = await get_recent_requests(initialized_db)
    assert rows[0]["system_prompt_hash"] == "abc123def456"


# ---------------------------------------------------------------------------
# get_recent_requests
# ---------------------------------------------------------------------------


async def test_recent_requests_ordered_newest_first(initialized_db: str):
    now = datetime.utcnow()
    for i in range(3):
        r = _record(cost_usd=float(i))
        r.timestamp = now + timedelta(seconds=i)
        await insert_request(initialized_db, r)

    rows = await get_recent_requests(initialized_db, limit=10)
    costs = [r["cost_usd"] for r in rows]
    assert costs == [2.0, 1.0, 0.0]


async def test_recent_requests_limit_respected(initialized_db: str):
    for _ in range(5):
        await insert_request(initialized_db, _record())
    rows = await get_recent_requests(initialized_db, limit=3)
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# get_total_cost
# ---------------------------------------------------------------------------


async def test_total_cost(initialized_db: str):
    for cost in [0.01, 0.02, 0.03]:
        await insert_request(initialized_db, _record(cost_usd=cost))
    total = await get_total_cost(initialized_db)
    assert abs(total - 0.06) < 1e-9


async def test_total_cost_empty_db(initialized_db: str):
    total = await get_total_cost(initialized_db)
    assert total == 0.0


async def test_total_cost_with_since_filter(initialized_db: str):
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()

    # Insert one in the past (before filter), one in the future (should not happen, but test)
    old_record = _record(cost_usd=0.10)
    old_record.timestamp = datetime.utcnow() - timedelta(days=2)
    await insert_request(initialized_db, old_record)

    new_record = _record(cost_usd=0.05)
    new_record.timestamp = datetime.utcnow()
    await insert_request(initialized_db, new_record)

    # Filter from yesterday: only the new record should count
    total = await get_total_cost(initialized_db, since=yesterday)
    assert abs(total - 0.05) < 1e-9


# ---------------------------------------------------------------------------
# get_usage_by_model
# ---------------------------------------------------------------------------


async def test_usage_by_model(initialized_db: str):
    await insert_request(initialized_db, _record(model="gpt-4o", input_tokens=100, output_tokens=50, cost_usd=0.01))
    await insert_request(initialized_db, _record(model="gpt-4o", input_tokens=200, output_tokens=80, cost_usd=0.02))
    rows = await get_usage_by_model(initialized_db)
    assert len(rows) == 1
    assert rows[0].model == "gpt-4o"
    assert rows[0].request_count == 2
    assert rows[0].total_input_tokens == 300
    assert abs(rows[0].total_cost_usd - 0.03) < 1e-9


async def test_usage_by_model_multiple_models(initialized_db: str):
    await insert_request(initialized_db, _record(model="gpt-4o", cost_usd=0.10))
    await insert_request(initialized_db, _record(model="gpt-4o-mini", cost_usd=0.01))
    rows = await get_usage_by_model(initialized_db)
    assert len(rows) == 2
    # Ordered by cost DESC
    assert rows[0].model == "gpt-4o"
    assert rows[1].model == "gpt-4o-mini"


async def test_usage_by_model_since_filter(initialized_db: str):
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()

    old = _record(model="gpt-4o", cost_usd=0.99)
    old.timestamp = datetime.utcnow() - timedelta(days=2)
    await insert_request(initialized_db, old)

    new = _record(model="gpt-4o-mini", cost_usd=0.01)
    await insert_request(initialized_db, new)

    rows = await get_usage_by_model(initialized_db, since=yesterday)
    assert len(rows) == 1
    assert rows[0].model == "gpt-4o-mini"


async def test_usage_by_model_empty_db(initialized_db: str):
    rows = await get_usage_by_model(initialized_db)
    assert rows == []


# ---------------------------------------------------------------------------
# get_usage_by_tag
# ---------------------------------------------------------------------------


async def test_usage_by_tag(initialized_db: str):
    await insert_request(initialized_db, _record(tags={"feature": "search"}, cost_usd=0.05, input_tokens=100, output_tokens=50))
    await insert_request(initialized_db, _record(tags={"feature": "search"}, cost_usd=0.03, input_tokens=80, output_tokens=40))
    await insert_request(initialized_db, _record(tags={"feature": "summary"}, cost_usd=0.10, input_tokens=200, output_tokens=100))

    rows = await get_usage_by_tag(initialized_db, tag_key="feature")
    tag_map = {r["tag"]: r for r in rows}

    assert "search" in tag_map
    assert "summary" in tag_map
    assert tag_map["search"]["request_count"] == 2
    assert abs(tag_map["search"]["total_cost_usd"] - 0.08) < 1e-9
    assert tag_map["summary"]["request_count"] == 1

    # Ordered by cost DESC
    assert rows[0]["tag"] == "summary"


async def test_usage_by_tag_untagged(initialized_db: str):
    await insert_request(initialized_db, _record(tags={}, cost_usd=0.01))
    rows = await get_usage_by_tag(initialized_db, tag_key="feature")
    assert len(rows) == 1
    assert rows[0]["tag"] == "(untagged)"


async def test_usage_by_tag_mixed(initialized_db: str):
    await insert_request(initialized_db, _record(tags={"feature": "chat"}, cost_usd=0.05))
    await insert_request(initialized_db, _record(tags={}, cost_usd=0.02))
    rows = await get_usage_by_tag(initialized_db, tag_key="feature")
    tag_map = {r["tag"]: r for r in rows}
    assert "chat" in tag_map
    assert "(untagged)" in tag_map


# ---------------------------------------------------------------------------
# get_total_request_count
# ---------------------------------------------------------------------------


async def test_request_count_empty(initialized_db: str):
    assert await get_total_request_count(initialized_db) == 0


async def test_request_count(initialized_db: str):
    for _ in range(7):
        await insert_request(initialized_db, _record())
    assert await get_total_request_count(initialized_db) == 7


async def test_request_count_since_filter(initialized_db: str):
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()

    old = _record()
    old.timestamp = datetime.utcnow() - timedelta(days=2)
    await insert_request(initialized_db, old)

    await insert_request(initialized_db, _record())
    await insert_request(initialized_db, _record())

    count = await get_total_request_count(initialized_db, since=yesterday)
    assert count == 2


# ---------------------------------------------------------------------------
# get_daily_cost
# ---------------------------------------------------------------------------


async def test_daily_cost(initialized_db: str):
    """Records from today should appear in the daily cost output."""
    await insert_request(initialized_db, _record(cost_usd=0.05))
    await insert_request(initialized_db, _record(cost_usd=0.03))

    rows = await get_daily_cost(initialized_db, days=7)
    assert len(rows) >= 1
    today_rows = [r for r in rows if r["request_count"] > 0]
    total_today = sum(r["total_cost_usd"] for r in today_rows)
    assert abs(total_today - 0.08) < 1e-9


async def test_daily_cost_empty_db(initialized_db: str):
    rows = await get_daily_cost(initialized_db, days=7)
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# get_requests_for_analysis
# ---------------------------------------------------------------------------


async def test_requests_for_analysis_fields(initialized_db: str):
    record = _record(
        tags={"team": "ml"},
        system_prompt_hash="hash123",
        input_tokens=500,
        output_tokens=100,
        cost_usd=0.02,
    )
    await insert_request(initialized_db, record)
    rows = await get_requests_for_analysis(initialized_db)
    assert len(rows) == 1
    row = rows[0]
    assert "id" in row
    assert "timestamp" in row
    assert "provider" in row
    assert "model" in row
    assert "input_tokens" in row
    assert "output_tokens" in row
    assert "cost_usd" in row
    assert "system_prompt_hash" in row
    assert row["tags"] == {"team": "ml"}
    assert row["input_tokens"] == 500


async def test_requests_for_analysis_limit(initialized_db: str):
    for _ in range(5):
        await insert_request(initialized_db, _record())
    rows = await get_requests_for_analysis(initialized_db, limit=3)
    assert len(rows) == 3


async def test_requests_for_analysis_since(initialized_db: str):
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()

    old = _record(cost_usd=0.99)
    old.timestamp = datetime.utcnow() - timedelta(days=2)
    await insert_request(initialized_db, old)

    await insert_request(initialized_db, _record(cost_usd=0.01))

    rows = await get_requests_for_analysis(initialized_db, since=yesterday)
    assert len(rows) == 1
    assert abs(rows[0]["cost_usd"] - 0.01) < 1e-9


# --- Phase 1: Data Foundation ---

import aiosqlite  # noqa: E402 — placed here to group with phase 1 tests


async def test_init_creates_ai_assets_table(tmp_db: str):
    """init_db should create the ai_assets table with all required columns."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_assets'"
        )
        row = await cursor.fetchone()
    assert row is not None, "ai_assets table should be created by init_db"


async def test_ai_assets_has_all_columns(tmp_db: str):
    """ai_assets table should have all required columns."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("PRAGMA table_info(ai_assets)")
        rows = await cursor.fetchall()
    col_names = {row[1] for row in rows}
    expected = {
        "id", "provider", "model_name", "endpoint_url", "api_key_hash",
        "owner_team", "project", "status", "risk_tier",
        "first_seen_at", "last_active_at", "monthly_spend_usd", "monthly_requests",
        "tags", "created_at", "updated_at",
    }
    assert expected <= col_names, f"Missing columns: {expected - col_names}"


async def test_ai_assets_status_check_constraint(tmp_db: str):
    """ai_assets.status CHECK constraint should reject invalid values."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO ai_assets (provider, model_name, endpoint_url, status, risk_tier, first_seen_at, last_active_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("openai", "gpt-4o", "https://api.openai.com", "bogus", "low", "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01"),
            )
            await db.commit()


async def test_ai_assets_risk_tier_check_constraint(tmp_db: str):
    """ai_assets.risk_tier CHECK constraint should reject invalid values."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO ai_assets (provider, model_name, endpoint_url, status, risk_tier, first_seen_at, last_active_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("openai", "gpt-4o", "https://api.openai.com", "shadow", "critical", "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01"),
            )
            await db.commit()


async def test_init_creates_provider_signatures_table(tmp_db: str):
    """init_db should create the provider_signatures table."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_signatures'"
        )
        row = await cursor.fetchone()
    assert row is not None, "provider_signatures table should be created by init_db"


async def test_provider_signatures_seeded_with_7_rows(tmp_db: str):
    """init_db should seed exactly 7 provider signatures."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM provider_signatures")
        row = await cursor.fetchone()
    assert row[0] == 7, f"Expected 7 provider signatures, got {row[0]}"


async def test_provider_signatures_providers(tmp_db: str):
    """All 7 expected providers should be present in provider_signatures."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("SELECT provider FROM provider_signatures ORDER BY provider")
        rows = await cursor.fetchall()
    providers = {row[0] for row in rows}
    expected = {"openai", "anthropic", "google", "azure_openai", "bedrock", "cohere", "mistral"}
    assert providers == expected, f"Missing: {expected - providers}, Extra: {providers - expected}"


async def test_provider_signatures_non_empty_fields(tmp_db: str):
    """Each seeded provider should have non-empty endpoint_pattern and header_signature."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT provider, endpoint_pattern, header_signature FROM provider_signatures"
        )
        rows = await cursor.fetchall()
    for row in rows:
        assert row["endpoint_pattern"], f"{row['provider']} missing endpoint_pattern"
        assert row["header_signature"], f"{row['provider']} missing header_signature"


async def test_init_creates_discovery_events_table(tmp_db: str):
    """init_db should create the discovery_events table."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='discovery_events'"
        )
        row = await cursor.fetchone()
    assert row is not None, "discovery_events table should be created by init_db"


async def test_discovery_events_event_type_check_constraint(tmp_db: str):
    """discovery_events.event_type CHECK constraint should reject invalid values."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO discovery_events (event_type, detected_at) VALUES (?, ?)",
                ("bogus_event", "2026-01-01T00:00:00"),
            )
            await db.commit()


async def test_discovery_events_update_trigger(tmp_db: str):
    """discovery_events UPDATE trigger should prevent updates (append-only).

    SQLite RAISE(ABORT, ...) raises IntegrityError via aiosqlite.
    """
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO discovery_events (event_type, detected_at) VALUES (?, ?)",
            ("new_asset_detected", "2026-01-01T00:00:00"),
        )
        await db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "UPDATE discovery_events SET event_type = 'asset_inactive' WHERE id = 1"
            )
            await db.commit()


async def test_discovery_events_delete_trigger(tmp_db: str):
    """discovery_events DELETE trigger should prevent deletes (append-only).

    SQLite RAISE(ABORT, ...) raises IntegrityError via aiosqlite.
    """
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO discovery_events (event_type, detected_at) VALUES (?, ?)",
            ("new_asset_detected", "2026-01-01T00:00:00"),
        )
        await db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute("DELETE FROM discovery_events WHERE id = 1")
            await db.commit()


async def test_discovery_events_allows_insert(tmp_db: str):
    """discovery_events should allow INSERT operations."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO discovery_events (event_type, detected_at) VALUES (?, ?)",
            ("new_asset_detected", "2026-01-01T00:00:00"),
        )
        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM discovery_events")
        row = await cursor.fetchone()
    assert row[0] == 1


async def test_discovery_events_nullable_asset_id(tmp_db: str):
    """discovery_events.asset_id should be nullable (org-level events)."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO discovery_events (event_type, asset_id, detected_at) VALUES (?, ?, ?)",
            ("new_asset_detected", None, "2026-01-01T00:00:00"),
        )
        await db.commit()
        cursor = await db.execute("SELECT asset_id FROM discovery_events WHERE id = 1")
        row = await cursor.fetchone()
    assert row[0] is None


async def test_indexes_created(tmp_db: str):
    """All required indexes should be created by init_db."""
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        rows = await cursor.fetchall()
    index_names = {r[0] for r in rows}
    expected_indexes = {
        "idx_ai_assets_provider",
        "idx_ai_assets_status",
        "idx_ai_assets_owner_team",
        "idx_ai_assets_last_active",
        "idx_discovery_events_asset_detected",
        "idx_provider_signatures_provider",
    }
    missing = expected_indexes - index_names
    assert not missing, f"Missing indexes: {missing}"


async def test_init_db_is_idempotent(tmp_db: str):
    """Calling init_db twice should not error or duplicate seed data."""
    await init_db(tmp_db)
    await init_db(tmp_db)
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM provider_signatures")
        row = await cursor.fetchone()
    assert row[0] == 7, f"Expected 7 after double init, got {row[0]}"


async def test_existing_requests_table_unaffected(tmp_db: str):
    """Extending init_db should not break the existing requests table."""
    await init_db(tmp_db)
    from burnlens.storage.database import insert_request
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
    )
    row_id = await insert_request(tmp_db, record)
    assert row_id > 0
