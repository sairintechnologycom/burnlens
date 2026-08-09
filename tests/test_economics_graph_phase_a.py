"""Economics-graph Phase A: agent/workflow attribution + tool-call and retry signals.

See .planning/economics-graph-roadmap-2026-08.md. Phase A is the identity layer
every later phase joins on -- outcomes (B), derived outcomes (C) and per-agent
anomaly baselines (D) all key off agent_id / workflow_id.

Cross-package wire-up for these tags is guarded separately in
tests/test_tag_plumbing_wired.py; this file covers collection and querying.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from burnlens.providers import get
from burnlens.proxy.interceptor import handle_request
from burnlens.storage.database import get_retry_stats, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.storage.queries import get_usage_by_tag


# ---------------------------------------------------------------------------
# count_tool_calls -- the three wire shapes in use
# ---------------------------------------------------------------------------

OPENAI_TWO_CALLS = {
    "choices": [
        {
            "message": {
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup"}},
                    {"id": "call_2", "function": {"name": "refund"}},
                ]
            }
        }
    ]
}

ANTHROPIC_ONE_CALL = {
    "content": [
        {"type": "text", "text": "let me check"},
        {"type": "tool_use", "id": "tu_1", "name": "lookup"},
    ]
}

GOOGLE_ONE_CALL = {
    "candidates": [
        {"content": {"parts": [{"text": "hi"}, {"functionCall": {"name": "lookup"}}]}}
    ]
}


@pytest.mark.parametrize(
    "provider_name,body,expected",
    [
        ("openai", OPENAI_TWO_CALLS, 2),
        ("anthropic", ANTHROPIC_ONE_CALL, 1),
        ("google", GOOGLE_ONE_CALL, 1),
        # Azure/Groq/Together/Mistral/xAI/DeepSeek all speak the OpenAI shape.
        ("groq", OPENAI_TWO_CALLS, 2),
    ],
)
def test_counts_tool_calls_per_wire_shape(provider_name, body, expected):
    assert get(provider_name).count_tool_calls(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": [{"message": {"content": "no tools here"}}]},
        {"content": [{"type": "text", "text": "plain"}]},
        {"candidates": [{"content": {"parts": [{"text": "plain"}]}}]},
    ],
)
def test_no_tool_calls_counts_zero(body):
    assert get("openai").count_tool_calls(body) == 0


@pytest.mark.parametrize(
    "body",
    [
        None,
        "not a dict",
        {"choices": "malformed"},
        {"choices": [None]},
        {"content": "malformed"},
        {"candidates": [{"content": {"parts": None}}]},
    ],
)
def test_malformed_bodies_never_raise(body):
    """Telemetry must never break a proxied request -- 0, never an exception."""
    assert get("openai").count_tool_calls(body) == 0


# ---------------------------------------------------------------------------
# End to end through handle_request
# ---------------------------------------------------------------------------


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, body: bytes):
        self._body = body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=self._body, headers={"content-type": "application/json"}
        )


async def _fetch_one(db_path: str) -> dict:
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
    return dict(row)


async def test_agent_and_workflow_tags_reach_storage_with_tool_calls(initialized_db):
    """A tagged request lands with attribution and a tool-call count."""
    response_body = {
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        **OPENAI_TWO_CALLS,
    }
    await handle_request(
        client=httpx.AsyncClient(transport=_Transport(json.dumps(response_body).encode())),
        provider=get("openai"),
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={
            "content-type": "application/json",
            "x-burnlens-tag-agent-id": "refund-agent",
            "x-burnlens-tag-workflow-id": "refund_review",
        },
        body_bytes=json.dumps({"model": "gpt-4o", "messages": []}).encode(),
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    # Storage happens in a background task on the proxy path.
    import asyncio

    for _ in range(10):
        await asyncio.sleep(0.05)

    row = await _fetch_one(initialized_db)
    tags = json.loads(row["tags"])
    assert tags["agent_id"] == "refund-agent"
    assert tags["workflow_id"] == "refund_review"
    assert row["tool_calls"] == 2


@pytest.mark.parametrize("header", ["x-burnlens-tag-agent-id", "x-burnlens-tag-agent_id"])
async def test_multiword_tag_accepts_both_header_spellings(initialized_db, header):
    """nginx drops headers containing underscores unless underscores_in_headers
    is on, so the hyphenated spelling has to work too."""
    import asyncio

    await handle_request(
        client=httpx.AsyncClient(transport=_Transport(json.dumps(
            {"model": "gpt-4o", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        ).encode())),
        provider=get("openai"),
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"content-type": "application/json", header: "refund-agent"},
        body_bytes=json.dumps({"model": "gpt-4o", "messages": []}).encode(),
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    for _ in range(10):
        await asyncio.sleep(0.05)

    row = await _fetch_one(initialized_db)
    assert json.loads(row["tags"])["agent_id"] == "refund-agent"


async def test_agent_tag_headers_never_forwarded_upstream(initialized_db):
    """agent_id/workflow_id are internal context -- the x-burnlens-* prefix rule
    must strip them like every other tag header."""
    captured: dict = {}

    class _Capture(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                content=json.dumps(
                    {"model": "gpt-4o", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                ).encode(),
                headers={"content-type": "application/json"},
            )

    await handle_request(
        client=httpx.AsyncClient(transport=_Capture()),
        provider=get("openai"),
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={
            "content-type": "application/json",
            "x-burnlens-tag-agent-id": "refund-agent",
            "x-burnlens-tag-workflow-id": "refund_review",
        },
        body_bytes=json.dumps({"model": "gpt-4o", "messages": []}).encode(),
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )

    sent = {k.lower() for k in captured["headers"]}
    assert "x-burnlens-tag-agent-id" not in sent
    assert "x-burnlens-tag-workflow-id" not in sent


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def _seed(db_path: str, **kwargs) -> None:
    await insert_request(db_path, RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        **kwargs,
    ))


async def test_spend_by_agent_and_workflow(initialized_db):
    """Cost per agent / per workflow needs no new query: get_usage_by_tag already
    groups by an arbitrary key in the tags JSON, and the local dashboard route
    /api/costs/by-tag?tag=<key> passes it straight through."""
    await _seed(initialized_db, cost_usd=1.0, tags={"agent_id": "a", "workflow_id": "w1"})
    await _seed(initialized_db, cost_usd=0.5, tags={"agent_id": "a", "workflow_id": "w2"})
    await _seed(initialized_db, cost_usd=0.25, tags={"agent_id": "b", "workflow_id": "w1"})

    by_agent = {r["tag"]: r for r in await get_usage_by_tag(initialized_db, "agent_id")}
    assert by_agent["a"]["total_cost_usd"] == pytest.approx(1.5)
    assert by_agent["a"]["request_count"] == 2
    assert by_agent["b"]["total_cost_usd"] == pytest.approx(0.25)

    by_workflow = {r["tag"]: r for r in await get_usage_by_tag(initialized_db, "workflow_id")}
    assert by_workflow["w1"]["total_cost_usd"] == pytest.approx(1.25)
    assert by_workflow["w2"]["total_cost_usd"] == pytest.approx(0.5)


async def test_untagged_spend_is_visible_not_dropped(initialized_db):
    """Unattributed spend must show up as its own bucket -- silently dropping it
    would make cost-per-agent look complete when it is not."""
    await _seed(initialized_db, cost_usd=1.0, tags={"agent_id": "a"})
    await _seed(initialized_db, cost_usd=9.0, tags={})

    by_agent = {r["tag"]: r for r in await get_usage_by_tag(initialized_db, "agent_id")}
    assert by_agent["(untagged)"]["total_cost_usd"] == pytest.approx(9.0)


async def test_retry_stats_counts_calls_following_a_failure(initialized_db):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    # trace-1: a failure then a successful retry 5s later -> 1 retry.
    await _seed(initialized_db, timestamp=now, status_code=500, cost_usd=0.0,
                trace_id="trace-1", tags={})
    await _seed(initialized_db, timestamp=now + timedelta(seconds=5), status_code=200,
                cost_usd=0.40, trace_id="trace-1", tags={})
    # trace-2: a clean call -> not a retry.
    await _seed(initialized_db, timestamp=now, status_code=200, cost_usd=0.10,
                trace_id="trace-2", tags={})
    # trace-3: retry arrives well outside the window -> not counted.
    await _seed(initialized_db, timestamp=now, status_code=500, cost_usd=0.0,
                trace_id="trace-3", tags={})
    await _seed(initialized_db, timestamp=now + timedelta(seconds=600), status_code=200,
                cost_usd=0.70, trace_id="trace-3", tags={})

    stats = await get_retry_stats(initialized_db, since=month_start, window_seconds=60)
    assert stats["retry_count"] == 1
    assert stats["retry_cost_usd"] == pytest.approx(0.40)


async def test_retry_stats_counts_each_retry_once(initialized_db):
    """Two prior failures in one trace must not double-count the single retry."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    await _seed(initialized_db, timestamp=now, status_code=500, cost_usd=0.0,
                trace_id="t", tags={})
    await _seed(initialized_db, timestamp=now + timedelta(seconds=1), status_code=500,
                cost_usd=0.0, trace_id="t", tags={})
    await _seed(initialized_db, timestamp=now + timedelta(seconds=2), status_code=200,
                cost_usd=0.30, trace_id="t", tags={})

    stats = await get_retry_stats(initialized_db, since=month_start, window_seconds=60)
    # The second 500 is itself a retry of the first, plus the 200 -> 2, not 3.
    assert stats["retry_count"] == 2
    assert stats["retry_cost_usd"] == pytest.approx(0.30)
