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
    """Same unit cost, far less traffic — totals collapse, the fix did nothing.

    One request is also below the sample floor, so the verdict is inconclusive
    rather than missed. Either way it is not a saving, which is the point.
    """
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    conn.requests = [_req(1.00, 7)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "inconclusive"
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
    conn.requests = [_req(0.50, 7 - i / 24) for i in range(40)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    assert verdict["status"] == "verified"
    assert verdict["baseline_cost_per_request"] == pytest.approx(1.00)
    assert verdict["current_cost_per_request"] == pytest.approx(0.50)
    assert verdict["delta_per_request"] == pytest.approx(0.50)
    # 0.50 saved/req * 40 req * (30/7)
    assert verdict["projected_monthly_savings_usd"] == pytest.approx(0.50 * 40 * (30 / 7))


@pytest.mark.asyncio
async def test_regression_is_missed_not_a_negative_verified_saving():
    ws = uuid4()
    conn = VerifyConn()
    conn.findings["fp-invoice"] = _resolved_finding(
        resolved_days_ago=8, baseline_cost=10.0, baseline_requests=10
    )
    conn.requests = [_req(1.50, 7 - i / 24) for i in range(40)]

    verdict = await verify_savings(conn, ws, "fp-invoice")
    # Never "verified": a rollup that sums verified savings would otherwise be
    # summing this regression into its own win column.
    assert verdict["status"] == "missed"
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


# ------------------------------------------------------------- savings rollup


class RollupConn(VerifyConn):
    """VerifyConn plus the two aggregate reads `savings_rollup` makes."""

    def __init__(self, open_waste=0.0, open_count=0):
        super().__init__()
        self.open_waste = open_waste
        self.open_count = open_count

    async def fetchrow(self, sql, *args):
        if "status IN ('open', 'acknowledged')" in sql:
            return {"waste": self.open_waste, "n": self.open_count}
        return await super().fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        if "baseline_requests IS NOT NULL" in sql:
            return [
                {
                    "fingerprint": fp,
                    "baseline_waste_usd": f.get("baseline_waste_usd"),
                    "baseline_window_days": f.get("baseline_window_days"),
                }
                for fp, f in self.findings.items()
            ]
        return []


def _rollup_finding(**kw):
    f = _resolved_finding(
        resolved_days_ago=kw.pop("resolved_days_ago", 8),
        baseline_cost=kw.pop("baseline_cost", 10.0),
        baseline_requests=kw.pop("baseline_requests", 10),
    )
    f.update(kw)
    return f


@pytest.mark.asyncio
async def test_predictions_are_scaled_to_monthly_before_they_are_compared():
    """The unit trap: a 7-day prediction next to a 30-day actual.

    `baseline_waste_usd` is measured over the baseline window; a verdict's
    actual is already extrapolated to 30 days. Comparing them raw silently
    reports a week against a month and understates realisation by ~4x.
    """
    from burnlens_cloud.findings import savings_rollup

    conn = RollupConn()
    conn.findings["fp-invoice"] = _rollup_finding(
        baseline_waste_usd=7.0, baseline_window_days=7
    )
    conn.requests = [_req(0.50, 7 - i / 24) for i in range(40)]

    out = await savings_rollup(conn, uuid4())

    assert out["resolved_predicted_monthly_usd"] == pytest.approx(7.0 * 30 / 7)
    assert out["verified_monthly_usd"] == pytest.approx(0.50 * 40 * (30 / 7))


@pytest.mark.asyncio
async def test_a_missed_fix_lands_in_the_denominator_and_not_the_numerator():
    """The whole reason the ratio is worth reading."""
    from burnlens_cloud.findings import savings_rollup

    conn = RollupConn()
    conn.findings["fp-invoice"] = _rollup_finding(
        baseline_waste_usd=7.0, baseline_window_days=7
    )
    # Cost per request went UP — a missed projection, not a negative saving.
    conn.requests = [_req(1.50, 7 - i / 24) for i in range(40)]

    out = await savings_rollup(conn, uuid4())

    assert out["verified_monthly_usd"] == pytest.approx(0.0)
    assert out["missed_predicted_monthly_usd"] == pytest.approx(7.0 * 30 / 7)
    assert out["realisation_pct"] == pytest.approx(0.0)
    assert out["counts"]["missed"] == 1


@pytest.mark.asyncio
async def test_pending_and_inconclusive_stay_out_of_the_ratio():
    """Neither has produced an answer, so neither should move the number."""
    from burnlens_cloud.findings import savings_rollup

    conn = RollupConn()
    conn.findings["fp-invoice"] = _rollup_finding(
        resolved_days_ago=1, baseline_waste_usd=7.0, baseline_window_days=7
    )

    out = await savings_rollup(conn, uuid4())

    assert out["verifying_predicted_monthly_usd"] == pytest.approx(7.0 * 30 / 7)
    # Undefined, not zero: 0% would read as "everything failed".
    assert out["realisation_pct"] is None


@pytest.mark.asyncio
async def test_open_findings_are_projection_only_never_verified_savings():
    """Nothing has been done about them, so they cannot have been realised."""
    from burnlens_cloud.findings import savings_rollup

    conn = RollupConn(open_waste=120.0, open_count=3)

    out = await savings_rollup(conn, uuid4())

    assert out["open_projected_monthly_usd"] == pytest.approx(120.0)
    assert out["verified_monthly_usd"] == pytest.approx(0.0)
    assert out["counts"]["open"] == 3
    assert out["realisation_pct"] is None
