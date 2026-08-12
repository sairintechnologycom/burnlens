"""Attribution coverage: the instrument that answers whether run/step grouping is possible.

`parent_span_id` has been captured since v1.18, but nothing read it — no CLI,
no dashboard route, no report. So a caller sending perfect `traceparent`
headers produced no visible signal to anyone, and the question "do traces
actually arrive?" could not be answered by waiting. This is the number that
answers it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from burnlens.analysis.economics import (
    get_economics_overview,
    get_trace_coverage,
    overview_to_dict,
)
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

TRACE_A = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACE_B = "0af7651916cd43dd8448eb211c80319c"


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
    path = str(tmp_path / "coverage.db")
    await init_db(path)
    return path


class TestCounting:
    async def test_counts_traced_parented_and_distinct(self, db):
        # Two requests in one run, one in another, one untraced. The distinct
        # count is what decides whether grouping is worth rendering: three
        # traced requests across two traces is two groups, not three.
        await insert_request(db, _record(trace_id=TRACE_A, parent_span_id="a" * 16))
        await insert_request(db, _record(trace_id=TRACE_A, parent_span_id="b" * 16))
        await insert_request(db, _record(trace_id=TRACE_B))  # trace, no caller span
        await insert_request(db, _record())                  # no traceparent at all

        cov = await get_trace_coverage(db, since=_since())
        assert cov.request_count == 4
        assert cov.traced_count == 3
        assert cov.parented_count == 2
        assert cov.distinct_traces == 2
        assert cov.traced_rate == 0.75

    async def test_untraced_traffic_reports_a_real_zero(self, db):
        await insert_request(db, _record())
        cov = await get_trace_coverage(db, since=_since())
        assert (cov.request_count, cov.traced_count, cov.distinct_traces) == (1, 0, 0)
        assert cov.traced_rate == 0.0
        assert cov.columns_missing is False

    async def test_empty_window_does_not_divide_by_zero(self, db):
        cov = await get_trace_coverage(db, since=_since())
        assert cov.request_count == 0
        assert cov.traced_rate == 0.0

    async def test_window_is_respected(self, db):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        await insert_request(db, _record(timestamp=old, trace_id=TRACE_A))
        await insert_request(db, _record(trace_id=TRACE_B))

        cov = await get_trace_coverage(db, since=_since(30))
        assert cov.request_count == 1
        assert cov.distinct_traces == 1


class TestUnmigratedDatabase:
    """A pre-trace database must not read as "no traces arrived".

    The two look identical from a zero, and telling them apart is the whole
    reason the figure exists — reporting a false zero would answer the gate
    wrongly and in the direction that kills the feature.
    """

    async def test_missing_columns_are_reported_not_zeroed(self, tmp_path):
        path = str(tmp_path / "legacy.db")
        async with aiosqlite.connect(path) as conn:
            await conn.execute(
                "CREATE TABLE requests (id INTEGER PRIMARY KEY, timestamp TEXT)"
            )
            await conn.execute(
                "INSERT INTO requests (timestamp) VALUES (?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            await conn.commit()

        cov = await get_trace_coverage(path, since=_since())
        assert cov.columns_missing is True
        assert cov.traced_count == 0


class TestReachesTheSurfaces:
    """The figure is useless if it only exists in the analysis layer."""

    async def test_overview_carries_coverage(self, db):
        await insert_request(db, _record(trace_id=TRACE_A, parent_span_id="a" * 16))
        overview = await get_economics_overview(db, since=_since())
        assert overview.trace_coverage.traced_count == 1
        assert overview.trace_coverage.parented_count == 1

    async def test_dashboard_api_serialises_coverage(self, db):
        await insert_request(db, _record(trace_id=TRACE_A, parent_span_id="a" * 16))
        payload = overview_to_dict(await get_economics_overview(db, since=_since()))
        assert payload["trace_coverage"] == {
            "request_count": 1,
            "traced_count": 1,
            "parented_count": 1,
            "distinct_traces": 1,
            "traced_rate": 1.0,
            "columns_missing": False,
        }
