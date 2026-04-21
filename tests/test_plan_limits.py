"""Phase 6 — plan_limits + resolve_limits end-to-end tests.

These tests hit a real Postgres because the resolver IS SQL. Mocking the pool
would only exercise the thin Python wrapper, not the COALESCE / JSONB `||` merge
behavior that PLAN-04 actually requires.

Requires DATABASE_URL to point at a reachable Postgres (the same one init_db
already migrates). If unreachable, the module is skipped so CI without a
database stays green.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest
import pytest_asyncio

try:
    import asyncpg  # noqa: F401  (import guard — if missing, module is unusable)
except ImportError:
    pytest.skip("asyncpg not installed", allow_module_level=True)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("DATABASE_URL not set — Phase 6 tests need a real Postgres", allow_module_level=True)


@pytest_asyncio.fixture(scope="module")
async def db():
    """Module-scoped: run init_db once, then tear down the pool at the end."""
    from burnlens_cloud import database as db_mod
    await db_mod.init_db()
    yield db_mod
    await db_mod.close_db()


@pytest_asyncio.fixture
async def workspace_factory(db):
    """Create a workspace with a unique api_key, return its UUID. Clean up after."""
    created: list[uuid.UUID] = []

    async def _make(plan: str = "free", limit_overrides: dict | None = None) -> uuid.UUID:
        ws_id = uuid.uuid4()
        api_key = f"bl_test_{uuid.uuid4().hex}"
        overrides_json = json.dumps(limit_overrides) if limit_overrides is not None else None
        # Phase 2c: plaintext owner_email + api_key columns are gone. Fixture
        # writes the encrypted / hash / last4 forms directly so the schema
        # invariants hold without pulling in PII_MASTER_KEY for tests.
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspaces (
                    id, name, owner_email_encrypted, owner_email_hash,
                    plan, api_key_hash, api_key_last4, limit_overrides
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                ws_id,
                f"test-{ws_id}",
                f"v1:test-encrypted-{ws_id}",
                f"test-hash-{ws_id}",
                plan,
                f"test-apikey-hash-{ws_id}",
                api_key[-4:],
                overrides_json,
            )
        created.append(ws_id)
        return ws_id

    yield _make

    # Teardown — remove every workspace this test created.
    async with db.pool.acquire() as conn:
        for ws_id in created:
            await conn.execute("DELETE FROM workspaces WHERE id = $1", ws_id)


# ---------------------------------------------------------------------------
# Success criterion 4: migrations are idempotent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_db_is_idempotent(db):
    """Running init_db() a second time must succeed and not duplicate seeds."""
    from burnlens_cloud import database as db_mod
    # db fixture already called init_db once. Call it again.
    await db_mod.init_db()

    async with db.pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM plan_limits")
    assert count == 3, f"expected exactly 3 seeded plans, got {count}"


# ---------------------------------------------------------------------------
# Success criterion 1: all three seed rows exist with exact CONTEXT.md values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_row_free(db):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM plan_limits WHERE plan = 'free'")
    assert row is not None, "free plan not seeded"
    assert row["monthly_request_cap"] == 10000
    assert row["seat_count"] == 1
    assert row["retention_days"] == 7
    assert row["api_key_count"] == 1
    assert row["paddle_price_id"] is None
    assert row["paddle_product_id"] is None
    gf = row["gated_features"]
    if isinstance(gf, str):
        gf = json.loads(gf)
    assert gf == {"custom_signatures": False, "team_seats": False, "otel_export": False}


@pytest.mark.asyncio
async def test_seed_row_cloud(db):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM plan_limits WHERE plan = 'cloud'")
    assert row is not None, "cloud plan not seeded"
    assert row["monthly_request_cap"] == 1000000
    assert row["seat_count"] == 1
    assert row["retention_days"] == 30
    assert row["api_key_count"] == 3
    assert row["paddle_price_id"] == "pri_01kpe2gkbz9w85btadnw8ckkyn"
    assert row["paddle_product_id"] == "pro_01kpe2dxvfmnp3xeaj37krsksm"
    gf = row["gated_features"]
    if isinstance(gf, str):
        gf = json.loads(gf)
    assert gf == {"custom_signatures": True, "team_seats": False, "otel_export": False}


@pytest.mark.asyncio
async def test_seed_row_teams(db):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM plan_limits WHERE plan = 'teams'")
    assert row is not None, "teams plan not seeded"
    assert row["monthly_request_cap"] == 10000000
    assert row["seat_count"] == 10
    assert row["retention_days"] == 90
    assert row["api_key_count"] == 25
    assert row["paddle_price_id"] == "pri_01kpe4f0aj537x609d6we7qpg7"
    assert row["paddle_product_id"] == "pro_01kpe4etanc8971v5eesj5npn7"
    gf = row["gated_features"]
    if isinstance(gf, str):
        gf = json.loads(gf)
    assert gf == {"custom_signatures": True, "team_seats": True, "otel_export": True}


# ---------------------------------------------------------------------------
# Success criterion 3: resolve_limits returns plan defaults for no-override workspace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_returns_plan_defaults_when_no_override(workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    ws_id = await workspace_factory(plan="cloud", limit_overrides=None)

    resolved = await resolve_limits(ws_id)
    assert resolved is not None
    assert resolved.plan == "cloud"
    assert resolved.monthly_request_cap == 1000000
    assert resolved.seat_count == 1
    assert resolved.retention_days == 30
    assert resolved.api_key_count == 3
    assert resolved.gated_features == {
        "custom_signatures": True,
        "team_seats": False,
        "otel_export": False,
    }


# ---------------------------------------------------------------------------
# Success criterion 2: scalar overrides supersede plan defaults (D-03 COALESCE)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scalar_override_supersedes_plan_default(workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    # Cloud plan default = 1_000_000 monthly_request_cap; override to 10x.
    ws_id = await workspace_factory(
        plan="cloud",
        limit_overrides={"monthly_request_cap": 10_000_000},
    )

    resolved = await resolve_limits(ws_id)
    assert resolved is not None
    assert resolved.monthly_request_cap == 10_000_000, "override did not supersede plan default"
    # Non-overridden fields must still reflect the plan default.
    assert resolved.seat_count == 1
    assert resolved.retention_days == 30
    assert resolved.api_key_count == 3


@pytest.mark.asyncio
async def test_empty_override_inherits_plan_default(workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    # Empty override dict → every scalar falls through to plan default via COALESCE.
    ws_id = await workspace_factory(plan="free", limit_overrides={})
    resolved = await resolve_limits(ws_id)
    assert resolved is not None
    assert resolved.monthly_request_cap == 10000  # inherited from free plan default


# ---------------------------------------------------------------------------
# D-02: NULL scalar on a plan row means unlimited (no cap applied)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_scalar_on_plan_means_unlimited(db, workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    # Insert a test-only plan row with every scalar set to NULL. Idempotent via
    # ON CONFLICT so reruns don't blow up. Teardown at end removes it.
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO plan_limits (
                plan, monthly_request_cap, seat_count, retention_days, api_key_count,
                paddle_price_id, paddle_product_id, gated_features
            ) VALUES (
                'enterprise_test', NULL, NULL, NULL, NULL,
                NULL, NULL, '{}'::jsonb
            )
            ON CONFLICT (plan) DO NOTHING
            """
        )
    try:
        ws_id = await workspace_factory(plan="enterprise_test")
        resolved = await resolve_limits(ws_id)
        assert resolved is not None
        # NULL scalar on plan → resolver yields None → "unlimited" for that field.
        assert resolved.monthly_request_cap is None
        assert resolved.seat_count is None
        assert resolved.retention_days is None
        assert resolved.api_key_count is None
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM plan_limits WHERE plan = 'enterprise_test'")


# ---------------------------------------------------------------------------
# D-04: gated_features merges per-flag, not whole-blob replace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gated_features_merge_per_flag(workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    # Cloud plan default: custom_signatures=true, team_seats=false, otel_export=false.
    # Override flips ONLY team_seats to true. Other flags must stay at plan default.
    ws_id = await workspace_factory(
        plan="cloud",
        limit_overrides={"gated_features": {"team_seats": True}},
    )

    resolved = await resolve_limits(ws_id)
    assert resolved is not None
    assert resolved.gated_features == {
        "custom_signatures": True,   # from plan default — must NOT be erased
        "team_seats": True,          # from override
        "otel_export": False,        # from plan default — must NOT be erased
    }, f"per-flag merge broken: got {resolved.gated_features}"


@pytest.mark.asyncio
async def test_gated_features_override_can_add_new_flag(workspace_factory):
    from burnlens_cloud.plans import resolve_limits
    # Free plan has all three flags false. Override introduces a new flag key not
    # in the plan default — JSONB `||` should add it to the merged output.
    ws_id = await workspace_factory(
        plan="free",
        limit_overrides={"gated_features": {"beta_feature_x": True}},
    )

    resolved = await resolve_limits(ws_id)
    assert resolved is not None
    assert resolved.gated_features["custom_signatures"] is False
    assert resolved.gated_features["team_seats"] is False
    assert resolved.gated_features["otel_export"] is False
    assert resolved.gated_features["beta_feature_x"] is True


# ---------------------------------------------------------------------------
# Success criterion 3 detail: single round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolver_returns_exactly_one_row(workspace_factory, db):
    """SELECT * FROM resolve_limits($1) must return exactly 1 row (single round-trip)."""
    ws_id = await workspace_factory(plan="teams")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM resolve_limits($1)", ws_id)
    assert len(rows) == 1, f"expected exactly 1 row from resolve_limits, got {len(rows)}"


@pytest.mark.asyncio
async def test_resolver_returns_none_for_nonexistent_workspace(db):
    from burnlens_cloud.plans import resolve_limits
    result = await resolve_limits(uuid.uuid4())
    assert result is None, "resolve_limits must return None for unknown workspace_id"
