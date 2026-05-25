"""Regression tests for the /v1/ingest wire format.

Reproduces the production bugs found by /qa on 2026-05-25:
  - ISSUE-001: OSS proxy sends api_key in X-API-Key header, not body field.
  - ISSUE-002: asyncpg pool needs a JSONB codec for tags-dict encoding.
  - ISSUE-003: OSS proxy sends tag_feature / tag_team / tag_customer as
               flat top-level fields, not nested in `tags`.

These tests pin the exact payload shape `burnlens/cloud/sync.py:push_batch`
emits today so the contract can't silently drift again.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _oss_proxy_payload_shape() -> dict:
    """The exact dict shape `burnlens.cloud.sync._row_to_payload` produces."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 100,
        "output_tokens": 50,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.000045,
        "duration_ms": 320,
        "status_code": 200,
        "system_prompt_hash": "abc123",
        # Flat tag_* fields — *not* nested under `tags`.
        "tag_feature": "chat",
        "tag_team": "backend",
        "tag_customer": "acme",
    }


@pytest_asyncio.fixture
async def ingest_client():
    """FastAPI app with only the ingest router + mocked DB."""
    from burnlens_cloud.ingest import router

    app = FastAPI()
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# ISSUE-001 — X-API-Key header fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_accepts_api_key_in_x_api_key_header(ingest_client):
    """OSS proxy posts {records:[...]} with X-API-Key header. Must NOT 422."""
    ws_id = str(uuid4())
    bulk_insert = AsyncMock()
    record_usage = AsyncMock()

    with patch(
        "burnlens_cloud.ingest.get_workspace_by_api_key",
        new=AsyncMock(return_value=(ws_id, "free")),
    ), patch(
        "burnlens_cloud.ingest._check_quota_or_raise", new=AsyncMock()
    ), patch(
        "burnlens_cloud.ingest.execute_query",
        new=AsyncMock(return_value=[{"otel_endpoint": None, "otel_api_key_encrypted": None, "otel_enabled": False}]),
    ), patch(
        "burnlens_cloud.ingest.execute_bulk_insert", new=bulk_insert
    ), patch(
        "burnlens_cloud.ingest._record_usage_and_maybe_notify", new=record_usage
    ):
        resp = await ingest_client.post(
            "/v1/ingest",
            headers={"X-API-Key": "bl_live_qa_test_key"},
            json={"records": [_oss_proxy_payload_shape()]},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"accepted": 1, "rejected": 0}
    bulk_insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_accepts_api_key_in_body(ingest_client):
    """Existing body shape still works after making api_key optional."""
    ws_id = str(uuid4())

    with patch(
        "burnlens_cloud.ingest.get_workspace_by_api_key",
        new=AsyncMock(return_value=(ws_id, "free")),
    ), patch(
        "burnlens_cloud.ingest._check_quota_or_raise", new=AsyncMock()
    ), patch(
        "burnlens_cloud.ingest.execute_query",
        new=AsyncMock(return_value=[{"otel_endpoint": None, "otel_api_key_encrypted": None, "otel_enabled": False}]),
    ), patch(
        "burnlens_cloud.ingest.execute_bulk_insert", new=AsyncMock()
    ), patch(
        "burnlens_cloud.ingest._record_usage_and_maybe_notify", new=AsyncMock()
    ):
        resp = await ingest_client.post(
            "/v1/ingest",
            json={
                "api_key": "bl_live_body_test_key",
                "records": [_oss_proxy_payload_shape()],
            },
        )

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_ingest_no_api_key_anywhere_returns_401(ingest_client):
    """No api_key in body and no X-API-Key header → 401, not 422."""
    resp = await ingest_client.post(
        "/v1/ingest",
        json={"records": [_oss_proxy_payload_shape()]},
    )

    assert resp.status_code == 401, resp.text
    assert "Missing API key" in resp.text


# ---------------------------------------------------------------------------
# ISSUE-003 — flat tag_* fields land inside the `tags` dict
# ---------------------------------------------------------------------------


def test_flat_tag_fields_are_lifted_into_tags_dict():
    """Pydantic model_validator re-nests tag_feature/team/customer."""
    from burnlens_cloud.models import RequestRecordBase

    record = RequestRecordBase(**_oss_proxy_payload_shape())

    assert record.tags == {
        "feature": "chat",
        "team": "backend",
        "customer": "acme",
    }


def test_explicit_tags_dict_wins_over_flat_fields():
    """When the caller already sends `tags`, the flat tag_* fields are ignored."""
    from burnlens_cloud.models import RequestRecordBase

    payload = _oss_proxy_payload_shape()
    payload["tags"] = {"feature": "explicit", "extra": "value"}

    record = RequestRecordBase(**payload)

    # Explicit dict survives unchanged — no merge from flat fields.
    assert record.tags == {"feature": "explicit", "extra": "value"}


def test_no_tag_fields_yields_empty_tags():
    """Records with no tag info at all keep the default empty dict."""
    from burnlens_cloud.models import RequestRecordBase

    payload = _oss_proxy_payload_shape()
    for k in ("tag_feature", "tag_team", "tag_customer"):
        payload.pop(k)

    record = RequestRecordBase(**payload)

    assert record.tags == {}


def test_partial_flat_tags_lift_only_present_keys():
    """Only the tag_* fields that are non-None get nested."""
    from burnlens_cloud.models import RequestRecordBase

    payload = _oss_proxy_payload_shape()
    payload["tag_team"] = None
    payload["tag_customer"] = None

    record = RequestRecordBase(**payload)

    assert record.tags == {"feature": "chat"}


# ---------------------------------------------------------------------------
# ISSUE-002 — JSONB codec is registered on the pool
# ---------------------------------------------------------------------------


def test_init_db_registers_jsonb_codec():
    """The pool init callback must register a jsonb codec.

    This is a structural check — actually exercising asyncpg requires a live
    Postgres which isn't in unit-test scope. We assert the wiring exists.
    """
    import inspect

    from burnlens_cloud import database

    src = inspect.getsource(database.init_db)
    assert "init=_register_jsonb_codec" in src, (
        "init_db must pass init=_register_jsonb_codec to asyncpg.create_pool — "
        "without it, dict→JSONB encoding in execute_bulk_insert 500s."
    )

    # Sanity-check the codec function shape.
    assert callable(database._register_jsonb_codec)
    src_codec = inspect.getsource(database._register_jsonb_codec)
    assert "set_type_codec" in src_codec
    assert '"jsonb"' in src_codec or "'jsonb'" in src_codec
