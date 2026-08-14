"""BL-F3: cloud savings verification — cost per request, never totals."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from burnlens_cloud.findings import verify_savings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VerifyConn:
    def __init__(self):
        self.findings: dict[str, dict] = {}
        self.requests: list[dict] = []

    async def fetchrow(self, sql, *args):
        if "FROM waste_findings" in sql:
            return self.findings.get(args[1])
        if "FROM request_records" in sql:
            since, until, subject = args[1], args[2], args[3]
            rows = []
            for r in self.requests:
                if r["ts"] < since or r["ts"] >= until:
                    continue
                if "tags->>'workflow_id'" in sql:
                    if (r.get("tags") or {}).get("workflow_id") != subject:
                        continue
                elif "model = $4" in sql and r.get("model") != subject:
                    continue
                rows.append(r)
            return {
                "spend": sum(float(r["cost_usd"]) for r in rows),
                "n": len(rows),
            }
        return None

    async def fetch(self, sql, *args):
        return []


def _resolved_finding(
    *,
    resolved_days_ago: float,
    baseline_cost: float,
    baseline_requests: int,
    status: str = "resolved",
) -> dict:
    resolved_at = _now() - timedelta(days=resolved_days_ago)
    return {
        "fingerprint": "fp-invoice",
        "title": "Model Overkill",
        "subject_type": "workflow",
        "subject_key": "invoice-gen",
        "status": status,
        "resolved_at": resolved_at,
        "baseline_cost_usd": baseline_cost,
        "baseline_requests": baseline_requests,
        "baseline_window_days": 7,
    }


def _req(cost: float, days_ago: float) -> dict:
    return {
        "cost_usd": cost,
        "ts": _now() - timedelta(days=days_ago),
        "tags": {"workflow_id": "invoice-gen"},
        "model": "claude-opus-5",
    }


@pytest.mark.asyncio
async def test_a_traffic_drop_is_not_mistaken_for_a_saving():
    """Same unit cost, 10× less traffic — totals collapse, the fix did nothing."""
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    conn.requests = [_req(1.00, 7)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "verified"
    assert verdict["baseline_cost_per_request"] == pytest.approx(1.00)
    assert verdict["current_cost_per_request"] == pytest.approx(1.00)
    assert verdict["delta_per_request"] == pytest.approx(0.0)
    assert verdict["projected_monthly_savings_usd"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_recent_fix_is_pending_with_days_remaining():
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=1, baseline_cost=10.0, baseline_requests=10
    )
    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "pending"
    assert verdict["days_remaining"] == pytest.approx(6.0, abs=0.1)


@pytest.mark.asyncio
async def test_silence_is_no_traffic():
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "no_traffic"
    assert verdict["projected_monthly_savings_usd"] is None


@pytest.mark.asyncio
async def test_genuine_unit_cost_drop_is_verified_from_current_rate():
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    conn.requests = [_req(0.50, 7 - i / 24) for i in range(10)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "verified"
    assert verdict["baseline_cost_per_request"] == pytest.approx(1.00)
    assert verdict["current_cost_per_request"] == pytest.approx(0.50)
    assert verdict["delta_per_request"] == pytest.approx(0.50)
    # 0.50 saved/req * 10 req * (30/7)
    assert verdict["projected_monthly_savings_usd"] == pytest.approx(0.50 * 10 * (30 / 7))


@pytest.mark.asyncio
async def test_regression_is_verified_negative_not_clamped():
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    conn.requests = [_req(1.50, 7 - i / 24) for i in range(10)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "verified"
    assert verdict["delta_per_request"] < 0
    assert verdict["projected_monthly_savings_usd"] < 0
    assert verdict["pct_change"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_missing_baseline_is_no_baseline():
    ws = uuid4()
    conn = VerifyConn()
    rec = _resolved_finding(resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10)
    rec["baseline_requests"] = None
    conn.findings["fp-invoice"] = rec
    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "no_baseline"
