"""BL-E3: does a fix actually reduce spend, and can the check be fooled?

A verdict is one of five states, and the split between them is what makes a
portfolio total honest:

* ``pending`` — the measurement window has not elapsed yet.
* ``no_traffic`` — nothing ran after the fix. Silence is not a saving.
* ``inconclusive`` — too few requests after the fix to judge (below
  ``MIN_VERIFY_REQUESTS``).
* ``verified`` — cost per request fell.
* ``missed`` — cost per request did not fall. **Not** a verified saving with a
  negative number attached; summing "verified" while regressions sit inside it
  labelled verified is how a savings figure stops being believable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.analysis.waste import ModelOverkillDetector
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.findings import (
    list_findings,
    savings_rollup,
    set_finding_status,
    sync_findings,
    verify_savings,
)
from burnlens.storage.models import RequestRecord


def _record(cost_usd: float, when: datetime, workflow: str = "invoice-gen"):
    return RequestRecord(
        provider="anthropic",
        model="claude-opus-5",
        request_path="/v1/messages",
        timestamp=when,
        input_tokens=1_000,
        output_tokens=50,
        cost_usd=cost_usd,
        duration_ms=400,
        status_code=200,
        tags={"workflow_id": workflow},
    )


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "savings.db")
    await init_db(path)
    return path


def _analysis_rows(count: int, cost: float) -> list[dict]:
    return [
        {
            "model": "claude-opus-5",
            "input_tokens": 1_000,
            "output_tokens": 50,
            "cost_usd": cost,
            "tags": {"workflow_id": "invoice-gen"},
            "system_prompt_hash": None,
        }
        for _ in range(count)
    ]


async def _seed_and_resolve(
    db_path: str,
    before_count: int,
    before_cost: float,
    resolved_days_ago: float,
) -> str:
    """Create a finding resolved N days ago with a known baseline.

    The baseline is written directly rather than captured live, because
    ``set_finding_status`` measures the window from the moment it runs and this
    fixture needs a resolve that happened in the past. Live capture has its own
    test (``test_resolving_captures_request_count_not_just_dollars``).
    """
    import aiosqlite

    resolved_at = datetime.now(timezone.utc) - timedelta(days=resolved_days_ago)

    findings = ModelOverkillDetector().run(_analysis_rows(before_count, before_cost))
    await sync_findings(db_path, findings)
    fingerprint = findings[0].fingerprint

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            UPDATE waste_findings
               SET status = 'resolved', resolved_at = ?,
                   baseline_waste_usd = estimated_waste_usd,
                   baseline_cost_usd = ?, baseline_requests = ?,
                   baseline_window_days = 7
             WHERE fingerprint = ?
            """,
            (
                resolved_at.isoformat(),
                before_cost * before_count,
                before_count,
                fingerprint,
            ),
        )
        await conn.commit()
    return fingerprint


@pytest.mark.asyncio
async def test_a_real_fix_is_verified(db):
    """Cost per request halves → verified saving."""
    fingerprint = await _seed_and_resolve(db, before_count=40, before_cost=1.00,
                                          resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(0.50, now - timedelta(days=7, minutes=i)))

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "verified"
    assert verdict.baseline_cost_per_request == pytest.approx(1.00)
    assert verdict.current_cost_per_request == pytest.approx(0.50)
    assert verdict.pct_change == pytest.approx(-50.0)
    assert verdict.projected_monthly_savings_usd > 0


@pytest.mark.asyncio
async def test_a_traffic_drop_is_not_mistaken_for_a_saving(db):
    """The trap this whole design exists to avoid.

    Same cost per request, but a fraction of the traffic. Total spend collapses;
    the fix did nothing. A totals-based comparison would call this a 90% win.

    One request is also too thin a sample to judge either way, so the verdict is
    inconclusive rather than missed — and inconclusive is still not a saving,
    which is the whole point.
    """
    fingerprint = await _seed_and_resolve(db, before_count=40, before_cost=1.00,
                                          resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    await insert_request(db, _record(1.00, now - timedelta(days=7)))

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "inconclusive"
    assert verdict.baseline_cost_per_request == pytest.approx(1.00)
    assert verdict.current_cost_per_request == pytest.approx(1.00)
    assert verdict.delta_per_request == pytest.approx(0.0)
    assert verdict.projected_monthly_savings_usd == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_an_unchanged_cost_per_request_is_missed_not_verified(db):
    """Enough traffic to judge, and nothing was saved. That is a missed fix."""
    fingerprint = await _seed_and_resolve(db, before_count=40, before_cost=1.00,
                                          resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(1.00, now - timedelta(days=7, minutes=i)))

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "missed"
    assert verdict.delta_per_request == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_silence_is_not_a_saving(db):
    """A workflow that stopped entirely would otherwise read as 100% saved."""
    fingerprint = await _seed_and_resolve(db, before_count=10, before_cost=1.00,
                                          resolved_days_ago=8)

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "no_traffic"
    assert verdict.projected_monthly_savings_usd is None


@pytest.mark.asyncio
async def test_a_regression_is_reported_as_such(db):
    """Cost per request went UP after the 'fix'.

    This must never carry the word "verified". A portfolio that sums verified
    savings would otherwise be summing this regression into its own win column.
    """
    fingerprint = await _seed_and_resolve(db, before_count=40, before_cost=1.00,
                                          resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(1.50, now - timedelta(days=7, minutes=i)))

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "missed"
    assert verdict.pct_change == pytest.approx(50.0)
    assert verdict.delta_per_request < 0
    assert verdict.projected_monthly_savings_usd < 0


@pytest.mark.asyncio
async def test_recent_fix_is_pending_not_judged(db):
    """Judging a fix an hour after it lands would be noise, not measurement."""
    fingerprint = await _seed_and_resolve(db, before_count=10, before_cost=1.00,
                                          resolved_days_ago=1)

    verdict = await verify_savings(db, fingerprint)

    assert verdict.status == "pending"
    assert verdict.days_remaining == pytest.approx(6.0, abs=0.1)


@pytest.mark.asyncio
async def test_reopened_finding_still_verifies_and_is_flagged(db):
    """A fix that did not hold is exactly the case worth reporting."""
    fingerprint = await _seed_and_resolve(db, before_count=40, before_cost=1.00,
                                          resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(1.00, now - timedelta(days=7, minutes=i)))

    # Detection finds the same waste again → reopens.
    await sync_findings(db, ModelOverkillDetector().run(_analysis_rows(40, 1.00)))

    stored = (await list_findings(db))[0]
    assert stored.status == "open"

    verdict = await verify_savings(db, fingerprint)
    assert verdict.reopened is True
    # The fix did not hold and cost per request never moved — missed, and the
    # reopened flag says why.
    assert verdict.status == "missed"


@pytest.mark.asyncio
async def test_resolving_captures_request_count_not_just_dollars(db):
    """Without the count there is no fair comparison to make later."""
    now = datetime.now(timezone.utc)
    for i in range(6):
        await insert_request(db, _record(0.25, now - timedelta(hours=i + 1)))

    findings = ModelOverkillDetector().run(_analysis_rows(6, 0.25))
    await sync_findings(db, findings)
    await set_finding_status(db, findings[0].fingerprint, "resolved")

    stored = (await list_findings(db, status="resolved"))[0]
    assert stored.baseline_requests == 6
    assert stored.baseline_cost_usd == pytest.approx(1.50)
    assert stored.baseline_window_days == 7


@pytest.mark.asyncio
async def test_unknown_fingerprint_returns_none(db):
    assert await verify_savings(db, "nope") is None


@pytest.mark.asyncio
async def test_local_rollup_puts_a_missed_fix_in_the_denominator(db):
    """Same contract as the cloud rollup: missed is not a negative verified."""
    await _seed_and_resolve(db, before_count=40, before_cost=1.00, resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(1.50, now - timedelta(days=7, minutes=i)))

    out = await savings_rollup(db)

    assert out["verified_monthly_usd"] == pytest.approx(0.0)
    assert out["missed_predicted_monthly_usd"] > 0
    assert out["realisation_pct"] == pytest.approx(0.0)
    assert out["counts"]["missed"] == 1


@pytest.mark.asyncio
async def test_local_rollup_pending_stays_out_of_the_ratio(db):
    await _seed_and_resolve(db, before_count=40, before_cost=1.00, resolved_days_ago=1)

    out = await savings_rollup(db)

    assert out["realisation_pct"] is None
    assert out["counts"].get("pending") == 1
    assert out["verifying_predicted_monthly_usd"] > 0
    assert out["verified_monthly_usd"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_economics_overview_carries_the_savings_portfolio(db):
    from burnlens.analysis.economics import get_economics_overview, overview_to_dict

    await _seed_and_resolve(db, before_count=40, before_cost=1.00, resolved_days_ago=8)
    now = datetime.now(timezone.utc)
    for i in range(40):
        await insert_request(db, _record(0.50, now - timedelta(days=7, minutes=i)))

    overview = await get_economics_overview(
        db, since=(now - timedelta(days=30)).isoformat()
    )
    assert overview.savings is not None
    assert overview.savings["counts"]["verified"] == 1
    assert overview.savings["verified_monthly_usd"] > 0
    payload = overview_to_dict(overview)
    assert payload["savings"]["counts"]["verified"] == 1
