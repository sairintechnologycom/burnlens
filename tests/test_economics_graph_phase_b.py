"""Economics-graph Phase B: outcomes and cost per accepted outcome (OSS side).

See .planning/economics-graph-roadmap-2026-08.md. The allocation rule under test:
a request is charged to the FIRST outcome of its workflow at-or-after it, within
a window. Spend with no such outcome is reported as unattributed rather than
dropped — a cost tool that quietly loses spend is worse than one that admits it
doesn't know where it went.

The cloud-side equivalents live in tests/test_outcomes_api.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.storage.database import (
    get_workflow_economics,
    insert_outcome,
    insert_request,
)
from burnlens.storage.models import Outcome, RequestRecord

# Relative to now, not a fixed date: the route test filters on a `days` lookback
# against the real clock, so a hardcoded T0 would silently fall out of range as
# it ages and start failing months from now.
T0 = datetime.now(timezone.utc) - timedelta(hours=6)
SINCE = (T0 - timedelta(days=1)).isoformat()


async def _req(db, minutes, cost, workflow="wf"):
    tags = {"workflow_id": workflow} if workflow else {}
    await insert_request(db, RequestRecord(
        provider="openai", model="gpt-4o", request_path="/v1",
        timestamp=T0 + timedelta(minutes=minutes), cost_usd=cost, tags=tags,
    ))


async def _outcome(db, oid, minutes, status, workflow="wf", value=None):
    return await insert_outcome(db, Outcome(
        outcome_id=oid, workflow_id=workflow, status=status,
        event_time=T0 + timedelta(minutes=minutes), business_value=value,
    ))


async def _one(db, **kw):
    rows = await get_workflow_economics(db, since=SINCE, **kw)
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------- allocation


async def test_cost_per_accepted_is_total_spend_over_accepted(initialized_db):
    """The headline number charges failures to the successes.

    Two attempts cost $1.50 total; one succeeded. One accepted result really
    cost $1.50, not the $1.00 of the winning attempt.
    """
    await _req(initialized_db, 0, 1.00)
    await _outcome(initialized_db, "o1", 1, "accepted")
    await _req(initialized_db, 10, 0.50)
    await _outcome(initialized_db, "o2", 11, "failed")

    row = await _one(initialized_db)
    assert row.cost_total_usd == pytest.approx(1.50)
    assert row.accepted_count == 1
    assert row.cost_per_accepted_usd == pytest.approx(1.50)
    # ...and the split shows how much of that was rework.
    assert row.cost_accepted_usd == pytest.approx(1.00)
    assert row.cost_rework_usd == pytest.approx(0.50)


async def test_request_is_charged_to_the_next_outcome_not_a_previous_one(initialized_db):
    """Allocation looks forward. Spend before an outcome belongs to it; spend
    after it belongs to the next one."""
    await _outcome(initialized_db, "early", 0, "accepted")
    await _req(initialized_db, 5, 2.00)          # after 'early', before 'late'
    await _outcome(initialized_db, "late", 10, "rejected")

    row = await _one(initialized_db)
    # The $2.00 belongs to 'late' (rejected), not to 'early' (accepted).
    assert row.cost_rework_usd == pytest.approx(2.00)
    assert row.cost_accepted_usd == pytest.approx(0.0)


async def test_spend_outside_the_window_is_unattributed(initialized_db):
    await _req(initialized_db, 0, 3.00)
    # Outcome lands 2h later; default window is 24h so it claims the cost.
    await _outcome(initialized_db, "o1", 120, "accepted")

    within = await _one(initialized_db)
    assert within.cost_accepted_usd == pytest.approx(3.00)
    assert within.cost_unattributed_usd == pytest.approx(0.0)

    # Same data, 60s window: the outcome is too late to claim it.
    outside = await _one(initialized_db, window_seconds=60)
    assert outside.cost_unattributed_usd == pytest.approx(3.00)
    assert outside.cost_accepted_usd == pytest.approx(0.0)
    # Total spend is unchanged — the money did not disappear, only its owner.
    assert outside.cost_total_usd == pytest.approx(3.00)


async def test_zero_outcome_workflow_reports_unattributed_not_zero_division(initialized_db):
    """Exit criterion: a workflow burning money with nothing accepted must show
    unattributed spend and a null unit cost, not a crash or a misleading 0."""
    await _req(initialized_db, 0, 9.00)

    row = await _one(initialized_db)
    assert row.accepted_count == 0
    assert row.cost_per_accepted_usd is None
    assert row.cost_unattributed_usd == pytest.approx(9.00)


async def test_workflow_with_outcomes_but_no_spend_still_appears(initialized_db):
    """Outcomes with no matching spend are a real signal (mis-tagged traffic),
    so the row must not vanish through an inner join."""
    await _outcome(initialized_db, "o1", 0, "accepted")

    row = await _one(initialized_db)
    assert row.accepted_count == 1
    assert row.cost_total_usd == pytest.approx(0.0)


async def test_untagged_spend_is_not_attributed_to_any_workflow(initialized_db):
    await _req(initialized_db, 0, 1.00)
    await _outcome(initialized_db, "o1", 1, "accepted")
    await _req(initialized_db, 2, 5.00, workflow=None)  # no workflow_id tag

    row = await _one(initialized_db)
    assert row.cost_total_usd == pytest.approx(1.00)


async def test_workflows_are_isolated_from_each_other(initialized_db):
    await _req(initialized_db, 0, 1.00, workflow="alpha")
    await _outcome(initialized_db, "a1", 1, "accepted", workflow="alpha")
    await _req(initialized_db, 0, 4.00, workflow="beta")
    await _outcome(initialized_db, "b1", 1, "accepted", workflow="beta")

    rows = {r.workflow_id: r for r in await get_workflow_economics(initialized_db, since=SINCE)}
    assert rows["alpha"].cost_per_accepted_usd == pytest.approx(1.00)
    assert rows["beta"].cost_per_accepted_usd == pytest.approx(4.00)


async def test_business_value_sums_for_accepted_only(initialized_db):
    await _outcome(initialized_db, "o1", 0, "accepted", value=100.0)
    await _outcome(initialized_db, "o2", 1, "accepted", value=50.0)
    await _outcome(initialized_db, "o3", 2, "rejected", value=999.0)

    row = await _one(initialized_db)
    assert row.business_value_accepted == pytest.approx(150.0)


# -------------------------------------------------------------- idempotency


async def test_duplicate_outcome_is_ignored(initialized_db):
    """Exit criterion: re-posting an outcome must not double-count.

    The denominator of cost-per-outcome is a count of outcomes, so a duplicate
    would silently halve the reported unit cost.
    """
    first = await _outcome(initialized_db, "same-id", 0, "accepted")
    second = await _outcome(initialized_db, "same-id", 5, "accepted")

    assert first > 0
    assert second == 0, "duplicate insert should report no new row"

    row = await _one(initialized_db)
    assert row.accepted_count == 1


async def test_duplicate_cannot_overwrite_status(initialized_db):
    """A replayed delivery must not be able to flip a recorded status."""
    await _outcome(initialized_db, "o1", 0, "accepted")
    await _outcome(initialized_db, "o1", 0, "failed")

    row = await _one(initialized_db)
    assert row.accepted_count == 1
    assert row.failed_count == 0


async def test_invalid_status_is_rejected_at_construction(initialized_db):
    with pytest.raises(ValueError):
        Outcome(outcome_id="x", workflow_id="wf", status="pending")


async def test_status_check_constraint_holds_at_the_db(initialized_db):
    """The dataclass guard is not the only line of defence — a writer that
    bypasses it still cannot put a bad status in the table."""
    import aiosqlite

    async with aiosqlite.connect(initialized_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO outcomes (outcome_id, workflow_id, status, event_time,"
                " created_at) VALUES ('x', 'wf', 'maybe', ?, ?)",
                (T0.isoformat(), T0.isoformat()),
            )
            await db.commit()


# ------------------------------------------------------------------- wiring


async def test_outcomes_table_created_by_init_db(initialized_db):
    """init_db must create the table — a fresh install has to work without
    anyone remembering to run a migration."""
    import aiosqlite

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='outcomes'"
        )
        assert await cursor.fetchone() is not None


async def test_local_dashboard_route_serves_economics(initialized_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from burnlens.dashboard.cloud_compat import outcomes_router

    await _req(initialized_db, 0, 2.00)
    await _outcome(initialized_db, "o1", 1, "accepted")

    app = FastAPI()
    app.state.db_path = initialized_db
    app.include_router(outcomes_router, prefix="/api/v1/outcomes")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/outcomes/summary?days=30")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["workflow_id"] == "wf"
    assert body[0]["cost_per_accepted_usd"] == pytest.approx(2.00)
