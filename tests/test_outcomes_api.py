"""Economics-graph Phase B, cloud side: /v1/outcomes and /api/v1/outcomes/summary.

Two layers here:

* Endpoint tests with ``execute_query`` mocked — auth, idempotency accounting,
  validation, and the divide-by-zero guard. These run everywhere.
* An integration test that executes the real allocation SQL against a live
  Postgres. It skips when none is reachable (CI has no Postgres service), but it
  is the only thing that actually proves the SQL is valid and agrees with the
  SQLite implementation in burnlens/storage/database.py. Two implementations of
  one rule is exactly where drift hides, so point a DSN at it when changing
  either:

      BURNLENS_TEST_PG_DSN=postgresql://... pytest tests/test_outcomes_api.py
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def outcomes_client():
    from burnlens_cloud.outcomes_api import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture
def valid_jwt_token():
    from burnlens_cloud.auth import encode_jwt

    return encode_jwt(str(uuid4()), str(uuid4()), "owner", "cloud")


def _outcome(**kw):
    body = {
        "outcome_id": "o1",
        "workflow_id": "refund_review",
        "status": "accepted",
        "event_time": "2026-08-09T12:00:00Z",
    }
    body.update(kw)
    return body


# ------------------------------------------------------------ POST /v1/outcomes


@pytest.mark.asyncio
async def test_post_requires_api_key(outcomes_client):
    resp = await outcomes_client.post("/v1/outcomes", json={"outcomes": [_outcome()]})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_rejects_invalid_api_key(outcomes_client):
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=None):
        resp = await outcomes_client.post(
            "/v1/outcomes",
            json={"outcomes": [_outcome()]},
            headers={"X-API-Key": "bl_live_nope"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_accepts_and_reports_duplicates(outcomes_client):
    """A suppressed insert returns no row — that is how a duplicate is counted
    without a second query, and it must be reported rather than hidden."""
    ws = str(uuid4())
    # First outcome inserts (RETURNING yields a row), second is a duplicate.
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=(ws, "pro")), \
         patch("burnlens_cloud.outcomes_api.execute_query", side_effect=[[{"id": 1}], []]):
        resp = await outcomes_client.post(
            "/v1/outcomes",
            json={"outcomes": [_outcome(outcome_id="a"), _outcome(outcome_id="b")]},
            headers={"X-API-Key": "bl_live_ok"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "duplicates": 1}


@pytest.mark.asyncio
async def test_within_batch_duplicates_collapse(outcomes_client):
    """The same id twice in one payload must hit the DB once, or the accepted
    count would depend on how the caller batched their retries."""
    ws = str(uuid4())
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=(ws, "pro")), \
         patch("burnlens_cloud.outcomes_api.execute_query", side_effect=[[{"id": 1}]]) as q:
        resp = await outcomes_client.post(
            "/v1/outcomes",
            json={"outcomes": [_outcome(outcome_id="dup"), _outcome(outcome_id="dup")]},
            headers={"X-API-Key": "bl_live_ok"},
        )

    assert resp.status_code == 200
    assert q.call_count == 1
    assert resp.json() == {"accepted": 1, "duplicates": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_status", ["pending", "ACCEPTED", "", "done"])
async def test_post_rejects_unknown_status(outcomes_client, bad_status):
    """Status drives the whole allocation split, so an unrecognised value must
    422 rather than land in the table and silently skew every metric."""
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=(str(uuid4()), "pro")):
        resp = await outcomes_client.post(
            "/v1/outcomes",
            json={"outcomes": [_outcome(status=bad_status)]},
            headers={"X-API-Key": "bl_live_ok"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_batch_is_a_noop(outcomes_client):
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=(str(uuid4()), "pro")):
        resp = await outcomes_client.post(
            "/v1/outcomes", json={"outcomes": []}, headers={"X-API-Key": "bl_live_ok"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 0, "duplicates": 0}


@pytest.mark.asyncio
async def test_outcomes_endpoint_is_csrf_exempt():
    """It authenticates by API key and is never cookie-authenticated, so the
    CSRF header requirement would only 403 legitimate machine callers.

    Asserted through the real middleware stack: a POST without X-Requested-With
    must reach authentication (401 on a bad key) rather than being turned away
    at 403 by CSRF.
    """
    from burnlens_cloud.main import get_app

    app = get_app()
    with patch("burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.post(
                "/v1/outcomes",
                json={"outcomes": [_outcome()]},
                headers={"X-API-Key": "bl_live_bad"},  # deliberately no X-Requested-With
            )

    assert resp.status_code != 403, (
        "/v1/outcomes is missing from csrf_exempt_prefixes — machine callers "
        "cannot send X-Requested-With and will be rejected before auth"
    )
    assert resp.status_code == 401


# -------------------------------------------------- GET /api/v1/outcomes/summary


@pytest.mark.asyncio
async def test_summary_requires_auth(outcomes_client):
    resp = await outcomes_client.get("/api/v1/outcomes/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_computes_cost_per_accepted(outcomes_client, valid_jwt_token):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [{
            "workflow_id": "refund_review",
            "cost_total": 25.0,
            "cost_accepted": 15.0,
            "cost_rework": 7.0,
            "cost_unattributed": 3.0,
            "accepted_count": 10,
            "rejected_count": 2,
            "failed_count": 1,
            "business_value_accepted": 500.0,
        }]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/summary",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert resp.status_code == 200
    row = resp.json()[0]
    # Total spend / accepted count — failures are charged to the successes.
    assert row["cost_per_accepted_usd"] == pytest.approx(2.5)
    assert row["cost_rework_usd"] == pytest.approx(7.0)
    assert row["cost_unattributed_usd"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_summary_returns_null_unit_cost_when_nothing_accepted(
    outcomes_client, valid_jwt_token
):
    """Exit criterion: a zero-outcome workflow reports unattributed spend and a
    null unit cost — never a divide-by-zero, never a misleading 0."""
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [{
            "workflow_id": "burning_money",
            "cost_total": 99.0,
            "cost_accepted": 0.0,
            "cost_rework": 0.0,
            "cost_unattributed": 99.0,
            "accepted_count": 0,
            "rejected_count": 0,
            "failed_count": 0,
            "business_value_accepted": None,
        }]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/summary",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    row = resp.json()[0]
    assert row["cost_per_accepted_usd"] is None
    assert row["cost_unattributed_usd"] == pytest.approx(99.0)


@pytest.mark.asyncio
async def test_summary_passes_window_through(outcomes_client, valid_jwt_token):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = []
        await outcomes_client.get(
            "/api/v1/outcomes/summary?window_seconds=300",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )
    assert q.call_args.args[3] == 300.0


# ------------------------------------------------------ live Postgres integration

_DSN = os.environ.get("BURNLENS_TEST_PG_DSN")

_PG_SCHEMA = """
DROP TABLE IF EXISTS outcomes;
DROP TABLE IF EXISTS request_records;
CREATE TABLE request_records (
    id BIGSERIAL PRIMARY KEY, workspace_id UUID NOT NULL, ts TIMESTAMPTZ NOT NULL,
    provider TEXT NOT NULL, model TEXT NOT NULL,
    cost_usd NUMERIC(12,8) NOT NULL DEFAULT 0, tags JSONB NOT NULL DEFAULT '{}');
CREATE TABLE outcomes (
    id BIGSERIAL PRIMARY KEY, workspace_id UUID NOT NULL, outcome_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted','rejected','failed')),
    business_value NUMERIC(18,6), currency TEXT, event_time TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL DEFAULT 'api', metadata JSONB NOT NULL DEFAULT '{}',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, outcome_id));
"""


@pytest.mark.asyncio
@pytest.mark.skipif(not _DSN, reason="set BURNLENS_TEST_PG_DSN to run the Postgres allocation test")
async def test_postgres_allocation_matches_sqlite():
    """Execute the real allocation SQL and check it against the same scenario
    the SQLite tests use, so the two implementations cannot silently diverge."""
    import asyncpg

    from burnlens_cloud.outcomes_api import _SUMMARY_SQL

    ws = str(uuid4())
    conn = await asyncpg.connect(_DSN)
    try:
        await conn.execute(_PG_SCHEMA)
        t0 = datetime.now(timezone.utc) - timedelta(hours=5)

        async def req(minutes, cost, wf="support_ticket"):
            await conn.execute(
                "INSERT INTO request_records (workspace_id, ts, provider, model, cost_usd, tags)"
                " VALUES ($1,$2,'openai','gpt-4o',$3,$4::jsonb)",
                ws, t0 + timedelta(minutes=minutes), cost,
                '{"workflow_id": "%s"}' % wf,
            )

        async def outcome(oid, minutes, status, wf="support_ticket"):
            await conn.execute(
                "INSERT INTO outcomes (workspace_id, outcome_id, workflow_id, status, event_time)"
                " VALUES ($1,$2,$3,$4,$5) ON CONFLICT (workspace_id, outcome_id) DO NOTHING",
                ws, oid, wf, status, t0 + timedelta(minutes=minutes),
            )

        await req(0, 1.00)
        await req(1, 0.50)
        await outcome("t1", 2, "accepted")
        await req(10, 0.25)
        await outcome("t2", 11, "failed")
        await req(20, 0.75)                     # no outcome -> unattributed
        await req(30, 9.00, wf="no_outcomes")   # zero-outcome workflow

        cutoff = t0 - timedelta(days=1)
        rows = {r["workflow_id"]: r for r in await conn.fetch(_SUMMARY_SQL, ws, cutoff, 86_400.0)}

        s = rows["support_ticket"]
        assert float(s["cost_total"]) == pytest.approx(2.50)
        assert float(s["cost_accepted"]) == pytest.approx(1.50)
        assert float(s["cost_rework"]) == pytest.approx(0.25)
        assert float(s["cost_unattributed"]) == pytest.approx(0.75)
        assert s["accepted_count"] == 1 and s["failed_count"] == 1

        z = rows["no_outcomes"]
        assert z["accepted_count"] == 0
        assert float(z["cost_unattributed"]) == pytest.approx(9.00)

        # Duplicate must not inflate the denominator.
        await outcome("t1", 2, "accepted")
        again = {r["workflow_id"]: r for r in await conn.fetch(_SUMMARY_SQL, ws, cutoff, 86_400.0)}
        assert again["support_ticket"]["accepted_count"] == 1

        # Outcome-only workflow must survive the FULL OUTER JOIN.
        await outcome("solo", 0, "accepted", wf="outcome_only")
        with_solo = {r["workflow_id"]: r for r in await conn.fetch(_SUMMARY_SQL, ws, cutoff, 86_400.0)}
        assert "outcome_only" in with_solo
        assert float(with_solo["outcome_only"]["cost_total"]) == pytest.approx(0.0)

        # A narrow window moves spend to unattributed without losing any of it.
        # At 90s: the request at t+1min is 60s before its outcome and still
        # claimed; the one at t+0 is 120s before and is not.
        narrow = {r["workflow_id"]: r for r in await conn.fetch(_SUMMARY_SQL, ws, cutoff, 90.0)}
        n = narrow["support_ticket"]
        assert float(n["cost_accepted"]) == pytest.approx(0.50)
        assert float(n["cost_rework"]) == pytest.approx(0.25)
        assert float(n["cost_unattributed"]) == pytest.approx(1.75)
        # The money did not disappear — only its owner changed.
        assert float(n["cost_total"]) == pytest.approx(2.50)
    finally:
        await conn.close()


# --------------------------------------------- GET /api/v1/outcomes/concentration


@pytest.mark.asyncio
async def test_concentration_requires_auth(outcomes_client):
    resp = await outcomes_client.get("/api/v1/outcomes/concentration")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_concentration_computes_shares_from_totals(
    outcomes_client, valid_jwt_token
):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [
            {
                "provider": "anthropic",
                "spend_usd": 80.0,
                "accepted_outcomes": 9,
                "workflows": 3,
                "sole_provider_workflows": 2,
                "total_spend": 100.0,
                "total_accepted": 10,
            },
            {
                "provider": "openai",
                "spend_usd": 20.0,
                "accepted_outcomes": 4,
                "workflows": 2,
                "sole_provider_workflows": 0,
                "total_spend": 100.0,
                "total_accepted": 10,
            },
        ]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/concentration",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert resp.status_code == 200
    a, o = resp.json()
    assert a["spend_share"] == pytest.approx(0.8)
    assert a["accepted_share"] == pytest.approx(0.9)
    # The dependency signal, and the reason spend share alone is not enough:
    # openai carries real spend but nothing depends on it alone.
    assert a["sole_provider_workflows"] == 2
    assert o["sole_provider_workflows"] == 0
    # Overlap is allowed to push the shares past 1.0 in total — an outcome two
    # providers contributed to counts for both.
    assert a["accepted_share"] + o["accepted_share"] > 1.0


@pytest.mark.asyncio
async def test_concentration_survives_empty_totals(outcomes_client, valid_jwt_token):
    """A window with rows but no attributed spend must report 0.0, never raise."""
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [{
            "provider": "openai",
            "spend_usd": 0.0,
            "accepted_outcomes": 0,
            "workflows": 1,
            "sole_provider_workflows": 1,
            "total_spend": 0.0,
            "total_accepted": 0,
        }]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/concentration",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert resp.status_code == 200
    assert resp.json()[0]["spend_share"] == 0.0
    assert resp.json()[0]["accepted_share"] == 0.0


@pytest.mark.asyncio
async def test_concentration_passes_window_through(outcomes_client, valid_jwt_token):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = []
        await outcomes_client.get(
            "/api/v1/outcomes/concentration?window_seconds=300",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )
    assert q.call_args.args[3] == 300.0


@pytest.mark.asyncio
@pytest.mark.skipif(not _DSN, reason="set BURNLENS_TEST_PG_DSN to run the Postgres concentration test")
async def test_postgres_concentration_counts_overlap_and_sole_dependency():
    """The mocked tests above check the arithmetic; only this one proves the SQL
    parses and that the DISTINCT/FILTER counting means what the model claims.

    Scenario: openai is the bigger spender but anthropic is the harder
    dependency, which is precisely the case a spend-ranked table cannot show.
    """
    import asyncpg

    from burnlens_cloud.outcomes_api import _CONCENTRATION_SQL

    ws = str(uuid4())
    conn = await asyncpg.connect(_DSN)
    try:
        await conn.execute(_PG_SCHEMA)
        t0 = datetime.now(timezone.utc) - timedelta(hours=5)

        async def req(minutes, cost, provider, wf):
            await conn.execute(
                "INSERT INTO request_records (workspace_id, ts, provider, model, cost_usd, tags)"
                " VALUES ($1,$2,$3,'m',$4,$5::jsonb)",
                ws, t0 + timedelta(minutes=minutes), provider, cost,
                '{"workflow_id": "%s"}' % wf,
            )

        async def outcome(oid, minutes, wf, status="accepted"):
            await conn.execute(
                "INSERT INTO outcomes (workspace_id, outcome_id, workflow_id, status, event_time)"
                " VALUES ($1,$2,$3,$4,$5)",
                ws, oid, wf, status, t0 + timedelta(minutes=minutes),
            )

        # wf_a: openai alone -> openai is the sole provider here.
        await req(0, 6.0, "openai", "wf_a")
        await outcome("o1", 1, "wf_a")
        # wf_b: both providers -> outcome o2 counts for BOTH of them.
        await req(10, 3.0, "openai", "wf_b")
        await req(11, 1.0, "anthropic", "wf_b")
        await outcome("o2", 12, "wf_b")
        # wf_c: anthropic alone, no accepted outcome -> sole dependency, no credit.
        await req(20, 2.0, "anthropic", "wf_c")

        rows = await conn.fetch(
            _CONCENTRATION_SQL, ws, t0 - timedelta(hours=1), 86_400.0
        )
        by = {r["provider"]: r for r in rows}

        assert float(by["openai"]["spend_usd"]) == pytest.approx(9.0)
        assert float(by["anthropic"]["spend_usd"]) == pytest.approx(3.0)
        # o1 and o2 for openai; only o2 for anthropic.
        assert by["openai"]["accepted_outcomes"] == 2
        assert by["anthropic"]["accepted_outcomes"] == 1
        # Two distinct outcomes total, NOT the 3 a naive sum of the two counts
        # would give -- o2 must not be double-counted in the denominator.
        assert by["openai"]["total_accepted"] == 2
        # Each provider is alone on exactly one workflow.
        assert by["openai"]["sole_provider_workflows"] == 1
        assert by["anthropic"]["sole_provider_workflows"] == 1
        assert by["openai"]["workflows"] == 2
        assert by["anthropic"]["workflows"] == 2
    finally:
        await conn.close()


# ------------------------------------------------ API-key auth on the read routes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/outcomes/summary", "/api/v1/outcomes/concentration"]
)
async def test_read_routes_accept_api_key(outcomes_client, path):
    """The machine that posts outcomes has no browser session, so it must be
    able to read the economics back with the key it wrote with — scoped to that
    key's workspace, never a wildcard."""
    ws = str(uuid4())
    with patch(
        "burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=(ws, "pro")
    ), patch("burnlens_cloud.outcomes_api.execute_query", return_value=[]) as q:
        resp = await outcomes_client.get(path, headers={"X-API-Key": "bl_live_ok"})

    assert resp.status_code == 200
    # The key's own workspace is what reaches the SQL — the isolation guarantee.
    assert q.call_args.args[1] == ws


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/outcomes/summary", "/api/v1/outcomes/concentration"]
)
async def test_read_routes_reject_bad_api_key(outcomes_client, path):
    """A rejected key must 401 and never reach the query — falling through to
    the JWT path would report a bad key as a permissions problem."""
    with patch(
        "burnlens_cloud.outcomes_api.get_workspace_by_api_key", return_value=None
    ), patch("burnlens_cloud.outcomes_api.execute_query") as q:
        resp = await outcomes_client.get(path, headers={"X-API-Key": "bl_live_nope"})

    assert resp.status_code == 401
    q.assert_not_called()


# ------------------------------------------- GET /api/v1/outcomes/coverage


def _cov_row(workflow_id, total, attributed, accepted=0.0, rework=0.0):
    return {
        "workflow_id": workflow_id,
        "cost_total": total,
        "cost_attributed": attributed,
        "cost_accepted": accepted,
        "cost_rework": rework,
    }


@pytest.mark.asyncio
async def test_coverage_requires_auth(outcomes_client):
    resp = await outcomes_client.get("/api/v1/outcomes/coverage")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_untagged_spend_is_separated_from_unattributed(
    outcomes_client, valid_jwt_token
):
    # The distinction that makes the number actionable: $85 has no workflow tag
    # at all (fix the caller), $5 is tagged but no outcome came back (post the
    # outcome). /outcomes/summary cannot see the $85 — it filters those rows out.
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [
            _cov_row(None, 85.0, 0.0),
            _cov_row("wf-a", 10.0, 10.0, accepted=10.0),
            _cov_row("wf-b", 5.0, 0.0),
        ]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/coverage",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["cost_untagged_usd"] == pytest.approx(85.0)
    assert body["cost_unattributed_usd"] == pytest.approx(5.0)
    assert body["cost_attributed_usd"] == pytest.approx(10.0)
    # Dollar-weighted, not request-weighted: 10 of 100 dollars reached an outcome.
    assert body["coverage_pct"] == pytest.approx(10.0)
    # And the three tiers have to account for every dollar, or the panel lies.
    assert (
        body["cost_attributed_usd"]
        + body["cost_unattributed_usd"]
        + body["cost_untagged_usd"]
        == pytest.approx(body["cost_total_usd"])
    )


@pytest.mark.asyncio
async def test_coverage_is_100_when_every_dollar_lands_on_an_outcome(
    outcomes_client, valid_jwt_token
):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [_cov_row("wf-a", 12.0, 12.0, accepted=9.0, rework=3.0)]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/coverage",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    body = resp.json()
    assert body["coverage_pct"] == pytest.approx(100.0)
    assert body["cost_untagged_usd"] == pytest.approx(0.0)
    # Rework is covered spend, not a gap — we know what it bought: a failure.
    assert body["cost_rework_usd"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_empty_workspace_coverage_does_not_divide_by_zero(
    outcomes_client, valid_jwt_token
):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = []
        resp = await outcomes_client.get(
            "/api/v1/outcomes/coverage",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["coverage_pct"] == 0.0


@pytest.mark.asyncio
async def test_coverage_passes_window_and_limits_the_breakdown(
    outcomes_client, valid_jwt_token
):
    with patch("burnlens_cloud.outcomes_api.execute_query") as q:
        q.return_value = [_cov_row(f"wf-{i}", 1.0, 1.0) for i in range(50)]
        resp = await outcomes_client.get(
            "/api/v1/outcomes/coverage?window_seconds=3600&limit=5",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert q.call_args.args[3] == 3600.0
    body = resp.json()
    assert len(body["by_workflow"]) == 5
    # The cap trims the breakdown only — the totals still cover every workflow.
    assert body["cost_total_usd"] == pytest.approx(50.0)
