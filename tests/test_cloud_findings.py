"""BL-F1: cloud waste_findings persistence + sync-on-read + lifecycle.

These tests exercise the findings module against an in-memory connection that
speaks the same method surface as asyncpg (fetch/fetchrow/fetchval/execute).
CI has no Postgres service; the SQL shape is still asserted via the statements
the module issues, and the lifecycle rules are the same ones pinned locally
in tests/test_waste_findings_lifecycle.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens.analysis.waste import WasteFinding, run_all_detectors
from burnlens_cloud.findings import (
    BASELINE_WINDOW_DAYS,
    records_to_detector_dicts,
    refresh_findings,
    set_finding_status,
    sync_findings,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _overkill_request(**over) -> dict:
    """Traffic that trips ModelOverkillDetector (expensive + short output)."""
    row = {
        "model": "claude-opus-5",
        "input_tokens": 1_000,
        "output_tokens": 50,
        "cost_usd": 0.10,
        "tags": {},
        "system_prompt_hash": None,
        "cache_read_tokens": 0,
        "ts": _now() - timedelta(hours=1),
        "workspace_id": None,
    }
    row.update(over)
    return row


class FakeConn:
    """Minimal asyncpg stand-in keyed off SQL fragments this module writes."""

    def __init__(self):
        self.findings: dict[tuple[str, str], dict] = {}
        self.requests: list[dict] = []
        self.sql_log: list[tuple[str, str, tuple]] = []

    def _ws(self, value) -> str:
        return str(value)

    async def fetchval(self, sql, *args):
        self.sql_log.append(("fetchval", sql, args))
        if "MAX(last_seen_at)" in sql:
            ws = self._ws(args[0])
            times = [
                r["last_seen_at"]
                for (w, _), r in self.findings.items()
                if w == ws
            ]
            return max(times) if times else None
        return None

    async def fetch(self, sql, *args):
        self.sql_log.append(("fetch", sql, args))
        if "FROM request_records" in sql:
            ws = self._ws(args[0])
            cutoff = args[1]
            until = args[2] if "ts < $3" in sql else None
            subject = args[3] if len(args) > 3 else None
            rows = []
            for r in self.requests:
                if self._ws(r["workspace_id"]) != ws:
                    continue
                if r["ts"] < cutoff:
                    continue
                if until is not None and r["ts"] >= until:
                    continue
                if subject is not None:
                    if "tags->>'workflow_id'" in sql:
                        tags = r.get("tags") or {}
                        if isinstance(tags, str):
                            tags = json.loads(tags)
                        if (tags or {}).get("workflow_id") != subject:
                            continue
                    elif "model = $4" in sql and r.get("model") != subject:
                        continue
                rows.append(r)
            if "COALESCE(SUM(cost_usd)" in sql:
                spend = sum(float(r.get("cost_usd") or 0) for r in rows)
                return [{"spend": spend, "n": len(rows)}]
            return rows
        if "FROM waste_findings" in sql:
            ws = self._ws(args[0])
            rows = [r for (w, _), r in self.findings.items() if w == ws]
            if "AND fingerprint = $2" in sql:
                fp = args[1]
                rows = [r for r in rows if r["fingerprint"] == fp]
            if "AND status = $2" in sql:
                rows = [r for r in rows if r["status"] == args[1]]
            return rows
        return []

    async def fetchrow(self, sql, *args):
        self.sql_log.append(("fetchrow", sql, args))
        if "FROM request_records" in sql:
            rows = await self.fetch(sql, *args)
            if not rows:
                return {"spend": 0, "n": 0}
            if "COALESCE(SUM(cost_usd)" in sql:
                return rows[0]
            return rows[0]
        if "FROM waste_findings" in sql:
            ws = self._ws(args[0])
            fp = args[1]
            return self.findings.get((ws, fp))
        return None

    async def execute(self, sql, *args):
        self.sql_log.append(("execute", sql, args))
        if "INSERT INTO waste_findings" in sql:
            rec = {
                "workspace_id": args[0],
                "fingerprint": args[1],
                "detector": args[2],
                "subject_type": args[3],
                "subject_key": args[4],
                "severity": args[5],
                "title": args[6],
                "description": args[7],
                "estimated_waste_usd": args[8],
                "affected_count": args[9],
                "evidence": args[10],
                "status": "open",
                "first_seen_at": args[11],
                "last_seen_at": args[12],
                "resolved_at": None,
                "baseline_waste_usd": None,
                "baseline_cost_usd": None,
                "baseline_requests": None,
                "baseline_window_days": None,
                "detection_count": 1,
                "detector_version": args[13],
            }
            self.findings[(self._ws(args[0]), args[1])] = rec
            return "INSERT 0 1"
        if "detection_count = detection_count + 1" in sql:
            ws, fp = self._ws(args[7]), args[8]
            rec = self.findings[(ws, fp)]
            rec["severity"] = args[0]
            rec["description"] = args[1]
            rec["estimated_waste_usd"] = args[2]
            rec["affected_count"] = args[3]
            rec["evidence"] = args[4]
            rec["last_seen_at"] = args[5]
            rec["status"] = args[6]
            rec["detection_count"] += 1
            return "UPDATE 1"
        if "SET status = 'resolved'" in sql:
            ws, fp = self._ws(args[4]), args[5]
            rec = self.findings[(ws, fp)]
            rec["status"] = "resolved"
            rec["resolved_at"] = args[0]
            rec["baseline_waste_usd"] = rec["estimated_waste_usd"]
            rec["baseline_cost_usd"] = args[1]
            rec["baseline_requests"] = args[2]
            rec["baseline_window_days"] = args[3]
            return "UPDATE 1"
        if "SET status = $1" in sql:
            rec = self.findings.get((self._ws(args[1]), args[2]))
            if rec is None:
                return "UPDATE 0"
            rec["status"] = args[0]
            return "UPDATE 1"
        return "UPDATE 0"


class FakePool:
    def __init__(self, conn: FakeConn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def test_tags_as_dict_adapter_keeps_workflow_scope():
    """A JSONB-as-string row must still produce a workflow-scoped finding."""
    rows = [
        _overkill_request(tags='{"workflow_id": "wf-x"}')
        for _ in range(3)
    ]
    adapted = records_to_detector_dicts(rows)
    assert all(isinstance(r["tags"], dict) for r in adapted)
    findings = run_all_detectors(adapted)
    scoped = [f for f in findings if f.subject_type == "workflow"]
    assert scoped, findings
    assert all(f.subject_key == "wf-x" for f in scoped)
    assert not any(f.subject_type == "model" for f in findings)


def test_adapter_casts_decimal_cost():
    adapted = records_to_detector_dicts(
        [_overkill_request(cost_usd=Decimal("0.10"))]
    )
    assert adapted[0]["cost_usd"] == 0.10
    assert isinstance(adapted[0]["cost_usd"], float)


# ---------------------------------------------------------------------------
# Detection + sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_inserts_findings_with_local_fingerprints():
    ws = uuid4()
    conn = FakeConn()
    conn.requests = [
        _overkill_request(workspace_id=ws, tags={"workflow_id": "invoice-gen"})
        for _ in range(3)
    ]
    await refresh_findings(conn, ws)

    assert conn.findings
    for rec in conn.findings.values():
        expected = WasteFinding(
            detector=rec["detector"],
            severity=rec["severity"],
            title=rec["title"],
            description=rec["description"],
            subject_type=rec["subject_type"],
            subject_key=rec["subject_key"],
        ).fingerprint
        assert rec["fingerprint"] == expected
        assert rec["status"] == "open"
        assert rec["detection_count"] == 1


@pytest.mark.asyncio
async def test_rerun_increments_detection_count_no_duplicates():
    ws = uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    assert candidates
    await sync_findings(conn, ws, candidates)
    await sync_findings(conn, ws, candidates)

    assert len(conn.findings) == len(candidates)
    for rec in conn.findings.values():
        assert rec["detection_count"] == 2


@pytest.mark.asyncio
async def test_resolved_redetected_reopens_and_keeps_resolved_at():
    ws = uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, ws, candidates)
    fp = candidates[0].fingerprint

    conn.requests = [
        _overkill_request(workspace_id=ws, tags={"workflow_id": "wf"})
        for _ in range(3)
    ]
    assert await set_finding_status(conn, ws, fp, "resolved")
    resolved_at = conn.findings[(str(ws), fp)]["resolved_at"]
    assert resolved_at is not None

    await sync_findings(conn, ws, candidates)
    rec = conn.findings[(str(ws), fp)]
    assert rec["status"] == "open"
    assert rec["resolved_at"] == resolved_at


@pytest.mark.asyncio
async def test_accepted_risk_never_reopens():
    ws = uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, ws, candidates)
    fp = candidates[0].fingerprint
    assert await set_finding_status(conn, ws, fp, "accepted_risk")

    await sync_findings(conn, ws, candidates)
    assert conn.findings[(str(ws), fp)]["status"] == "accepted_risk"


@pytest.mark.asyncio
async def test_resolve_snapshots_baselines_from_seeded_traffic():
    ws = uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, ws, candidates)
    fp = candidates[0].fingerprint
    conn.requests = [
        _overkill_request(workspace_id=ws, tags={"workflow_id": "wf"}, cost_usd=0.25)
        for _ in range(4)
    ]

    assert await set_finding_status(conn, ws, fp, "resolved")
    rec = conn.findings[(str(ws), fp)]
    assert rec["baseline_waste_usd"] == rec["estimated_waste_usd"]
    assert rec["baseline_cost_usd"] == pytest.approx(1.0)
    assert rec["baseline_requests"] == 4
    assert rec["baseline_window_days"] == BASELINE_WINDOW_DAYS
    assert rec["resolved_at"] is not None


@pytest.mark.asyncio
async def test_staleness_short_circuit_skips_detectors():
    ws = uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, ws, candidates)

    with patch(
        "burnlens_cloud.findings.run_all_detectors",
        side_effect=AssertionError("detectors must not run inside the hour"),
    ) as mocked:
        await refresh_findings(conn, ws)
        mocked.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_isolation_at_sync_layer():
    a, b = uuid4(), uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, a, candidates)
    # B has no findings
    from burnlens_cloud.findings import list_findings

    a_rows = await list_findings(conn, a)
    b_rows = await list_findings(conn, b)
    assert a_rows
    assert b_rows == []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def findings_client():
    from burnlens_cloud.findings_api import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture
def jwt_for():
    from burnlens_cloud.auth import encode_jwt

    def _make(workspace_id=None, role="owner", plan="cloud"):
        return encode_jwt(str(workspace_id or uuid4()), str(uuid4()), role, plan)

    return _make


@pytest.mark.asyncio
async def test_status_post_without_requested_with_is_rejected(findings_client, jwt_for):
    ws = uuid4()
    conn = FakeConn()
    token = jwt_for(ws)
    with patch("burnlens_cloud.findings_api.get_pool", return_value=FakePool(conn)):
        resp = await findings_client.post(
            "/api/v1/findings/abc/status",
            json={"status": "acknowledged"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
    assert "X-Requested-With" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_status_post_invalid_status_is_422(findings_client, jwt_for):
    ws = uuid4()
    conn = FakeConn()
    token = jwt_for(ws)
    with patch("burnlens_cloud.findings_api.get_pool", return_value=FakePool(conn)):
        resp = await findings_client.post(
            "/api/v1/findings/abc/status",
            json={"status": "nope"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Requested-With": "test",
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_http_workspace_isolation(findings_client, jwt_for):
    a, b = uuid4(), uuid4()
    conn = FakeConn()
    candidates = run_all_detectors(
        [_overkill_request(tags={"workflow_id": "wf"}) for _ in range(3)]
    )
    await sync_findings(conn, a, candidates)

    token_b = jwt_for(b)
    with patch("burnlens_cloud.findings_api.get_pool", return_value=FakePool(conn)):
        resp = await findings_client.get(
            "/api/v1/findings",
            headers={"Authorization": f"Bearer {token_b}"},
        )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_findings_and_waste_alerts_return_open_rows(findings_client, jwt_for):
    ws = uuid4()
    conn = FakeConn()
    conn.requests = [
        _overkill_request(workspace_id=ws, tags={"workflow_id": "wf"})
        for _ in range(3)
    ]
    token = jwt_for(ws)
    with patch("burnlens_cloud.findings_api.get_pool", return_value=FakePool(conn)):
        listed = await findings_client.get(
            "/api/v1/findings",
            headers={"Authorization": f"Bearer {token}"},
        )
        alerts = await findings_client.get(
            "/api/v1/waste-alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert listed.status_code == 200
    body = listed.json()
    assert body
    assert "id" in body[0] and body[0]["id"] == body[0]["fingerprint"]
    assert alerts.status_code == 200
    assert alerts.json()
    assert alerts.json()[0]["id"] == body[0]["fingerprint"]


@pytest.mark.asyncio
async def test_findings_requires_auth(findings_client):
    assert (await findings_client.get("/api/v1/findings")).status_code == 401


@pytest.mark.asyncio
async def test_waste_alerts_ungated_on_free(findings_client, jwt_for):
    """G17: findings/waste-alerts are available on every plan."""
    ws = uuid4()
    token = jwt_for(ws, role="viewer", plan="free")
    with patch(
        "burnlens_cloud.findings_api.get_pool", return_value=FakePool(FakeConn())
    ):
        resp = await findings_client.get(
            "/api/v1/waste-alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == []
