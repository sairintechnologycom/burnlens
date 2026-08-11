"""BL-E2: economics KPIs, and the overlap semantics they must not misrepresent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.analysis.economics import get_economics_overview, get_error_spend
from burnlens.analysis.waste import run_all_detectors
from burnlens.storage.database import init_db, insert_outcome, insert_request
from burnlens.storage.findings import sync_findings
from burnlens.storage.models import Outcome, RequestRecord
from burnlens.storage.queries import get_requests_for_analysis


def _since(days: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _record(**overrides) -> RequestRecord:
    base = dict(
        provider="anthropic",
        model="claude-opus-5",
        request_path="/v1/messages",
        timestamp=datetime.now(timezone.utc),
        input_tokens=1_000,
        output_tokens=50,
        cost_usd=0.10,
        duration_ms=400,
        status_code=200,
        tags={},
    )
    base.update(overrides)
    return RequestRecord(**base)


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "economics.db")
    await init_db(path)
    return path


async def _detect_and_store(db_path: str) -> None:
    requests = await get_requests_for_analysis(db_path, since=_since())
    await sync_findings(db_path, run_all_detectors(requests))


# ---------------------------------------------------------------------------
# Error spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_spend_counts_only_failed_requests(db):
    for _ in range(3):
        await insert_request(db, _record(status_code=200, cost_usd=1.00))
    for _ in range(2):
        await insert_request(db, _record(status_code=500, cost_usd=0.50))

    spend, count = await get_error_spend(db, _since())

    assert count == 2
    assert spend == pytest.approx(1.00)


@pytest.mark.asyncio
async def test_error_spend_is_not_subtracted_from_total(db):
    """Error spend is a dimension of total spend, not a slice carved out of it."""
    await insert_request(db, _record(status_code=200, cost_usd=1.00))
    await insert_request(db, _record(status_code=429, cost_usd=0.25))

    overview = await get_economics_overview(db, since=_since())

    assert overview.total_spend_usd == pytest.approx(1.25)
    assert overview.error_spend_usd == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Overlap: the reason these are a rate + dimensions, not buckets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waste_categories_overlap_and_do_not_sum_to_total(db):
    """One request can trip several detectors, each estimating its own share.

    So per-detector waste must never be presented as a disjoint breakdown that
    adds up to detected waste.
    """
    # Trips context bloat AND history bloat AND model overkill at once.
    for _ in range(12):
        await insert_request(
            db,
            _record(
                model="claude-opus-5",
                input_tokens=10_000,
                output_tokens=50,
                prompt_history_tokens=6_000,
                cost_usd=1.00,
            ),
        )
    await _detect_and_store(db)

    overview = await get_economics_overview(db, since=_since())

    # These same 12 requests are counted by three separate detectors.
    assert len(overview.waste_by_detector) >= 3
    assert sum(overview.waste_by_detector.values()) > overview.total_spend_usd


@pytest.mark.asyncio
async def test_waste_rate_is_clamped_when_estimates_exceed_spend(db):
    """Overlapping multipliers can exceed 100% of a request's cost.

    Printing a >100% waste rate would destroy trust in the number faster than
    any missing feature, so it clamps and says it clamped.
    """
    for _ in range(12):
        await insert_request(
            db,
            _record(
                model="claude-opus-5",
                input_tokens=10_000,
                output_tokens=50,
                prompt_history_tokens=6_000,
                prompt_rag_tokens=9_000,
                prompt_tools_tokens=4_000,
                cost_usd=1.00,
            ),
        )
    await _detect_and_store(db)

    overview = await get_economics_overview(db, since=_since())

    # $12 spent; five detectors estimate ~$31 avoidable between them.
    assert sum(overview.waste_by_detector.values()) > overview.total_spend_usd * 2
    assert overview.waste_estimate_clamped is True
    assert overview.waste_rate == 1.0
    assert overview.detected_waste_usd == pytest.approx(overview.total_spend_usd)


@pytest.mark.asyncio
async def test_resolved_findings_leave_the_waste_rate(db):
    """The rate has to be able to go down, or nobody acts on it."""
    from burnlens.storage.findings import list_findings, set_finding_status

    for _ in range(12):
        await insert_request(
            db, _record(input_tokens=10_000, output_tokens=50, cost_usd=1.00)
        )
    await _detect_and_store(db)

    before = await get_economics_overview(db, since=_since())
    assert before.waste_rate > 0

    for finding in await list_findings(db):
        await set_finding_status(db, finding.fingerprint, "resolved")

    after = await get_economics_overview(db, since=_since())
    assert after.waste_rate == 0.0
    assert after.open_finding_count == 0


# ---------------------------------------------------------------------------
# Cost per accepted outcome — must reuse the existing allocation engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_per_accepted_charges_failures_to_successes(db):
    """Total workflow spend over accepted count — matching get_workflow_economics.

    A second, subtly different definition here would put two contradictory
    cost-per-outcome figures in the same product.
    """
    now = datetime.now(timezone.utc)
    for _ in range(4):
        await insert_request(
            db,
            _record(
                timestamp=now - timedelta(minutes=10),
                cost_usd=0.50,
                tags={"workflow_id": "invoice-gen"},
            ),
        )
    await insert_outcome(
        db,
        Outcome(
            outcome_id="pr-1",
            workflow_id="invoice-gen",
            status="accepted",
            event_time=now,
        ),
    )

    overview = await get_economics_overview(db, since=_since())

    assert overview.accepted_count == 1
    # $2.00 of spend, one accepted outcome — failures charged to the success.
    assert overview.cost_per_accepted_usd == pytest.approx(2.00)


@pytest.mark.asyncio
async def test_cost_per_accepted_is_none_not_zero_without_outcomes(db):
    """Zero would read as 'free'. None reads as 'not measured yet'."""
    await insert_request(db, _record(cost_usd=1.00, tags={"workflow_id": "x"}))

    overview = await get_economics_overview(db, since=_since())

    assert overview.accepted_count == 0
    assert overview.cost_per_accepted_usd is None


@pytest.mark.asyncio
async def test_empty_database_reports_zeroes_not_errors(db):
    overview = await get_economics_overview(db, since=_since())

    assert overview.total_spend_usd == 0.0
    assert overview.waste_rate == 0.0
    assert overview.cost_per_accepted_usd is None
