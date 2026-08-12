"""BL-E5 slice 1: the caller's span id survives from traceparent into the DB."""

import aiosqlite
import pytest

from burnlens.proxy.interceptor import _extract_parent_span_id, _resolve_canonical_metadata
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_real_traceparent_yields_both_ids():
    meta = _resolve_canonical_metadata({"traceparent": TRACEPARENT}, {})
    assert meta["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert meta["parent_span_id"] == "00f067aa0ba902b7"


def test_no_traceparent_yields_neither():
    meta = _resolve_canonical_metadata({}, {})
    assert meta["trace_id"] is None
    assert meta["parent_span_id"] is None


def test_all_zero_parent_is_absent():
    # The spec's "no parent" sentinel must not be stored as a real span.
    assert _extract_parent_span_id({"traceparent": "00-" + "a" * 32 + "-" + "0" * 16 + "-01"}) is None
    # A tag/header trace id has no span concept at all.
    assert _extract_parent_span_id({"x-trace-id": "trace-uuid-123"}) is None
    # Malformed span segments are dropped, not stored half-parsed.
    assert _extract_parent_span_id({"traceparent": "00-" + "a" * 32 + "-tooshort-01"}) is None
    assert _extract_parent_span_id({"traceparent": "00-" + "a" * 32 + "-zzzzzzzzzzzzzzzz-01"}) is None


@pytest.mark.asyncio
async def test_parent_span_id_round_trips_through_storage(tmp_path):
    db_path = str(tmp_path / "t.db")
    await init_db(db_path)
    await insert_request(
        db_path,
        RequestRecord(
            provider="anthropic",
            model="claude-opus-5",
            request_path="/v1/messages",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            parent_span_id="00f067aa0ba902b7",
        ),
    )
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT trace_id, parent_span_id FROM requests")
        assert await cursor.fetchone() == (
            "4bf92f3577b34da6a3ce929d0e0e4736",
            "00f067aa0ba902b7",
        )
