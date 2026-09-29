"""Phase 3A: explicit local relationships preserve ledger charges and workspace scope."""
from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import aiosqlite
import httpx
import pytest

from burnlens.config import BurnLensConfig, CacheConfig
from burnlens.providers.openai import openai_provider
from burnlens.proxy.interceptor import handle_request, _resolve_canonical_metadata
from burnlens.proxy.server import get_app
from burnlens.storage.agent_economics import (
    get_workflow_run_graph, insert_agent_run, insert_workflow_run,
)
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import (
    REQUEST_RELATION_FIELDS, AgentRun, RequestRecord, WorkflowRun,
)
from burnlens.storage.wal import WriteAheadLog, recover_wal


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "graph.db")
    await init_db(path)
    await insert_workflow_run(path, WorkflowRun(
        workflow_run_id="wf-run", workflow_id="workflow", workspace_id="A",
    ))
    return path


def record(event_id=None, **overrides):
    return RequestRecord(provider="openai", model="gpt-4o", request_path="/v1/chat/completions",
                         event_id=event_id, workspace_id=overrides.pop("workspace_id", "A"),
                         workflow_run_id=overrides.pop("workflow_run_id", "wf-run"), **overrides)


async def test_graph_reconciles_deduplicates_and_never_resolves_other_workspace(db):
    # Phase 2 permits scoped IDs registered before telemetry begins referencing them.
    await insert_workflow_run(db, WorkflowRun(workflow_run_id="wf-run", workflow_id="other", workspace_id="B"))
    await insert_agent_run(db, AgentRun(run_id="parent", agent_id="planner", workspace_id="A",
                                       workflow_run_id="wf-run"))
    await insert_agent_run(db, AgentRun(run_id="child", agent_id="worker", workspace_id="A",
                                       parent_run_id="parent"))
    a = record("a", cost_usd=1, run_id="parent")
    await insert_request(db, a)
    await insert_request(db, record("b", cost_usd=2, parent_event_id="a", retry_of_event_id="a",
                                    run_id="child", workflow_run_id=None))
    await insert_request(db, record("c", cost_usd=3, fallback_of_event_id="b"))
    await insert_request(db, record("d", cost_usd=4))
    assert await insert_request(db, a) == 0
    await insert_request(db, record("foreign", cost_usd=99, workspace_id="B", parent_event_id="a"))
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"] == dict(request_count=4, ledger_cost_usd=10, linked_cost_usd=5,
                                   unlinked_cost_usd=5, unpriced_count=0, unknown_pricing_count=0,
                                   unresolved_count=0, invalid_count=0, cost_complete=True)
    assert len(graph["requests"]) == 4
    assert {r["run_id"] for r in graph["agent_runs"]} == {"parent", "child"}
    assert any(e["kind"] == "child_run" for e in graph["edges"])
    foreign = await get_workflow_run_graph(db, "wf-run", "B")
    assert foreign["totals"]["ledger_cost_usd"] == 99
    assert foreign["references"][0]["resolution"] == "unresolved"
    assert all(e["target"] != "a" and e["source"] != "a" for e in foreign["edges"])
    assert await get_workflow_run_graph(db, "wf-run", "C") is None


async def test_late_arrival_pagination_external_links_and_unknown_prices(db):
    instant = datetime.now(timezone.utc)
    await insert_request(db, record("b", parent_event_id="a", cost_usd=2, timestamp=instant))
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["unresolved_count"] == 1
    await insert_request(db, record("a", cost_usd=1, timestamp=instant))
    await insert_request(db, record("external", workflow_run_id=None, cost_usd=20))
    await insert_request(db, record("c", parent_event_id="external", pricing_class="unpriced", cost_usd=0))
    graph = await get_workflow_run_graph(db, "wf-run", "A", limit=1, offset=1)
    assert graph["requests"][0]["event_id"] == "b"
    assert graph["references"][0]["resolution"] == "outside_page"
    assert graph["totals"]["ledger_cost_usd"] == 3
    assert graph["totals"]["linked_cost_usd"] == 2
    assert not graph["totals"]["cost_complete"]
    assert graph["pagination"]["truncated"]
    graph = await get_workflow_run_graph(db, "wf-run", "A", limit=1, offset=2)
    assert graph["references"][0]["resolution"] == "outside_selection"
    with pytest.raises(ValueError):
        await get_workflow_run_graph(db, "wf-run", "", limit=501)


@pytest.mark.parametrize("links", [
    {"parent_event_id": "bad\nvalue"}, {"parent_event_id": "x" * 129},
    {"parent_event_id": "self"}, {"parent_event_id": ""}, {"parent_event_id": 42},
    {"retry_of_event_id": "a", "fallback_of_event_id": "a"},
])
async def test_invalid_links_do_not_drop_charges(db, links):
    await insert_request(db, record("self", cost_usd=7, **links))
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute("SELECT * FROM requests WHERE event_id='self'")).fetchone()
    assert row["cost_usd"] == 7
    assert all(row[column] is None for column in REQUEST_RELATION_FIELDS)


async def test_cycles_are_rejected_atomically_and_historical_cycles_suppressed(db):
    await asyncio.gather(insert_request(db, record("a", parent_event_id="b", cost_usd=1)),
                         insert_request(db, record("b", parent_event_id="a", cost_usd=2)))
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["ledger_cost_usd"] == 3
    assert len(graph["references"]) == 1
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE requests SET parent_event_id = CASE event_id WHEN 'a' THEN 'b' ELSE 'a' END")
        await conn.commit()
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["invalid_count"] == 2
    assert graph["totals"]["linked_cost_usd"] == 0
    assert all(link["resolution"] == "invalid" for link in graph["references"])


async def test_missing_workspace_stays_unlinked(db):
    await insert_request(db, record("a", workspace_id=None, parent_event_id="b", cost_usd=1))
    await insert_request(db, record("b", parent_event_id="a", cost_usd=2))
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["request_count"] == 1
    assert graph["totals"]["unresolved_count"] == 1


async def test_migration_canonical_and_wal_recovery(db, tmp_path, monkeypatch):
    await insert_request(db, record("old", cost_usd=1))
    async with aiosqlite.connect(db) as conn:
        for column in REQUEST_RELATION_FIELDS:
            await conn.execute(f"DROP INDEX idx_requests_{column}")
            await conn.execute(f"ALTER TABLE requests DROP COLUMN {column}")
        await conn.commit()
    await init_db(db)
    await init_db(db)
    legacy = record(cost_usd=4)
    await insert_request(db, legacy)
    assert legacy.event_id
    rec = record("linked", parent_event_id=legacy.event_id, retry_of_event_id=legacy.event_id,
                 run_id="run", agent_id="agent", task_id="task", action_id="action", cost_usd=2)
    converted = RequestRecord.from_event(rec.to_event())
    for name in (*REQUEST_RELATION_FIELDS, "workflow_run_id", "run_id", "agent_id", "task_id", "action_id"):
        assert getattr(converted, name) == getattr(rec, name)
    fallback = record("fallback", fallback_of_event_id="linked", parent_event_id=legacy.event_id)
    assert RequestRecord.from_event(fallback.to_event()).fallback_of_event_id == "linked"
    wal = WriteAheadLog(str(tmp_path / "events.jsonl"), str(tmp_path / "dlq.jsonl"))
    await wal.append_event(converted)
    assert await recover_wal(wal, db) == 1
    assert await insert_request(db, converted) == 0
    # Simulate the pre-3A dataclass field filter used by older WAL readers.
    payload = wal._record_to_dict(converted)
    with monkeypatch.context() as patch:
        patch.setattr("burnlens.storage.wal.fields", lambda cls: [
            f for f in fields(cls) if f.name not in REQUEST_RELATION_FIELDS
        ])
        old_reader = wal._dict_to_record(payload)
        assert old_reader.cost_usd == 2
        assert old_reader.event_id == "linked"
        assert old_reader.parent_event_id is None
    no_id = record(cost_usd=3)
    await wal.append_event(no_id)
    assert no_id.event_id
    assert await recover_wal(wal, db) == 1
    assert await insert_request(db, no_id) == 0
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["ledger_cost_usd"] == 10


def test_causal_ids_have_no_environment_or_tag_fallback(monkeypatch):
    monkeypatch.setenv("BURNLENS_PARENT_EVENT_ID", "sticky")
    monkeypatch.setenv("BURNLENS_TAG_RETRY_OF_EVENT_ID", "sticky")
    meta = _resolve_canonical_metadata({}, {"parent_event_id": "sticky"})
    assert all(meta[column] is None for column in REQUEST_RELATION_FIELDS)


async def test_legacy_rows_without_event_or_price_identity_remain_unknown(db):
    await insert_request(db, record("old", cost_usd=2))
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE requests SET event_id=NULL, pricing_class=NULL")
        await conn.commit()
    graph = await get_workflow_run_graph(db, "wf-run", "A")
    assert graph["totals"]["ledger_cost_usd"] == 2
    assert graph["totals"]["unknown_pricing_count"] == 1
    assert not graph["totals"]["cost_complete"]
    assert graph["requests"][0]["event_id"] is None
    assert graph["requests"][0]["ledger_row_id"]
    assert graph["edges"] == []


@pytest.mark.parametrize("streaming,cache_hit", [(False, False), (True, False), (False, True), (True, True)])
async def test_proxy_headers_match_eventual_ledger_on_every_path(db, monkeypatch, streaming, cache_hit):
    await insert_request(db, record("predecessor"))
    response_json = {"id": "provider-id", "model": "gpt-4o", "choices": [
        {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
    upstream_headers = []
    def upstream(req):
        upstream_headers.append(dict(req.headers))
        if streaming:
            body = "data: " + json.dumps(response_json) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response_json)
    if cache_hit:
        monkeypatch.setattr("burnlens.cache.manager.SemanticCacheManager.lookup_exact",
                            AsyncMock(return_value=(json.dumps(response_json).encode(), "openai", "gpt-4o")))
    config = BurnLensConfig(db_path=db, cache=CacheConfig(enabled=cache_hit))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        status, headers, _, stream = await handle_request(
            client=client, provider=openai_provider, path="/proxy/openai/v1/chat/completions",
            method="POST", headers={"Authorization": "Bearer test", "Content-Type": "application/json",
                "X-BurnLens-Workspace-Id": "A", "X-BurnLens-Tag-Workflow-Run-Id": "wf-run",
                "X-BurnLens-Parent-Event-Id": "predecessor",
                "X-BurnLens-Retry-Of-Event-Id": "predecessor", "X-BurnLens-Event-Id": "spoofed"},
            body_bytes=json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}],
                                   "stream": streaming}).encode(), query_string="", db_path=db, config=config,
        )
        assert status == 200
        event_id = headers["x-burnlens-event-id"]
        assert event_id != "spoofed"
        if stream is not None:
            async for _ in stream:
                pass
        for _ in range(100):
            async with aiosqlite.connect(db) as conn:
                conn.row_factory = aiosqlite.Row
                row = await (await conn.execute("SELECT * FROM requests WHERE event_id=?", (event_id,))).fetchone()
            if row:
                break
            await asyncio.sleep(0.01)
        assert row is not None
        assert row["parent_event_id"] == row["retry_of_event_id"] == "predecessor"
        assert row["workflow_run_id"] == "wf-run"
        assert bool(row["cache_hit"]) == cache_hit
    assert bool(upstream_headers) != cache_hit
    assert all(not key.startswith("x-burnlens-") for h in upstream_headers for key in h)


async def test_graph_route_is_mounted_in_production_app_and_requires_scope(db):
    await insert_request(db, record("a", cost_usd=1))
    app = get_app(BurnLensConfig(db_path=db))
    app.state.db_path = db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/workflow-runs/wf-run/graph"
        assert (await client.get(path)).status_code == 422
        assert (await client.get(path, params={"workspace_id": "B"})).status_code == 404
        assert (await client.get(path, params={"workspace_id": "A", "limit": 501})).status_code == 422
        response = await client.get(path, params={"workspace_id": "A"},
                                    headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 200
        assert response.json()["totals"]["ledger_cost_usd"] == 1
        assert "x-burnlens-event-id" in response.headers["access-control-expose-headers"].lower()
