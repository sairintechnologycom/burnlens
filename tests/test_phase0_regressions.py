"""Regression tests verifying Phase 0: Repo Baseline & Release Safety."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from burnlens.cli import app as cli_app
from burnlens.config import BurnLensConfig, KeyBudgetEntry
from burnlens.feature_flags import is_enabled
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.proxy.server import get_app
from burnlens.storage.queries import get_recent_requests


# ---------------------------------------------------------------------------
# 1. Feature Flag Tests
# ---------------------------------------------------------------------------
def test_feature_flags_enabled_disabled(monkeypatch):
    """Test feature flag checks using environment variables."""
    # Ensure starting state
    monkeypatch.delenv("BURNLENS_OTEL_ENABLED", raising=False)
    assert not is_enabled("otel")

    # Set to true
    monkeypatch.setenv("BURNLENS_OTEL_ENABLED", "true")
    assert is_enabled("otel")

    # Set to truthy alternatives
    monkeypatch.setenv("BURNLENS_OTEL_ENABLED", "1")
    assert is_enabled("otel")
    monkeypatch.setenv("BURNLENS_OTEL_ENABLED", "yes")
    assert is_enabled("otel")

    # Set to false
    monkeypatch.setenv("BURNLENS_OTEL_ENABLED", "false")
    assert not is_enabled("otel")


# ---------------------------------------------------------------------------
# 2. Mock Transport for Proxy Verification
# ---------------------------------------------------------------------------
class MockAsyncTransport(httpx.AsyncBaseTransport):
    """Captures requests and returns canned completions or streaming chunks."""

    def __init__(self, response_json: dict | None = None, is_streaming: bool = False):
        self.captured_request: httpx.Request | None = None
        self._response_json = response_json or {}
        self._is_streaming = is_streaming

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        if self._is_streaming:
            # Yield streaming chunks
            async def stream_generator():
                chunks = [
                    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
                    b"data: [DONE]\n\n",
                ]
                for chunk in chunks:
                    yield chunk
                    await asyncio.sleep(0.01)

            return httpx.Response(
                status_code=200,
                content=stream_generator(),
                headers={"content-type": "text/event-stream"},
            )
        else:
            content = json.dumps(self._response_json).encode()
            return httpx.Response(
                status_code=200,
                content=content,
                headers={"content-type": "application/json"},
            )


# Helper to wait for proxy background tasks (logging/alerts) to flush
async def _flush_tasks():
    for _ in range(5):
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# 3. Proxy Hot-Path & DB Writing Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_proxy_passthrough_and_db_write(initialized_db: str):
    """Verify non-streaming request forwards correctly and logs to local DB."""
    response_payload = {
        "id": "chatcmpl-regression",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
        "usage": {"prompt_tokens": 15, "completion_tokens": 10},
    }
    transport = MockAsyncTransport(response_payload)
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

    req_body = json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}).encode()

    status, headers, body, stream = await handle_request(
        client=client,
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"content-type": "application/json", "x-burnlens-tag-team": "qa"},
        body_bytes=req_body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    await _flush_tasks()

    assert status == 200
    assert stream is None
    assert body is not None
    assert json.loads(body)["id"] == "chatcmpl-regression"

    # Verify database log
    requests = await get_recent_requests(initialized_db, limit=5)
    assert len(requests) == 1
    req = requests[0]
    assert req["provider"] == "openai"
    assert req["model"] == "gpt-4o"
    assert req["input_tokens"] == 15
    assert req["output_tokens"] == 10
    assert req["tags"] == {"team": "qa"}


@pytest.mark.asyncio
async def test_proxy_streaming_passthrough(initialized_db: str):
    """Verify streaming chunks are captured and pass through the proxy."""
    transport = MockAsyncTransport(is_streaming=True)
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

    req_body = json.dumps({"model": "gpt-4o", "messages": [], "stream": True}).encode()

    status, headers, body, stream = await handle_request(
        client=client,
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"content-type": "application/json"},
        body_bytes=req_body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    assert status == 200
    assert stream is not None

    # Collect streaming chunks
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    await _flush_tasks()

    assert len(chunks) > 0
    assert b"[DONE]" in chunks[-1]

    # Verify stream stats got logged
    requests = await get_recent_requests(initialized_db, limit=5)
    assert len(requests) == 1
    req = requests[0]
    assert req["input_tokens"] == 10
    assert req["output_tokens"] == 5


# ---------------------------------------------------------------------------
# 4. Budget Cap (429 Block) Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_budget_cap_enforcement_prevents_upstream(initialized_db: str):
    """Verify HTTP 429 block is enforced before making upstream provider call."""
    # Create configuration with a tiny daily limit
    config = BurnLensConfig()
    config.db_path = initialized_db
    config.alerts.api_key_budgets.default = KeyBudgetEntry(daily_usd=0.0001)

    # Seed some usage in the DB to exceed the cap
    from burnlens.storage.database import insert_request
    from burnlens.storage.models import RequestRecord
    from burnlens.keys import register_key
    from datetime import datetime, timezone

    # Register the key to map to a label
    await register_key(initialized_db, "sk-test-label", "openai", "sk-test-key")

    # Insert a past record with $1 cost to exhaust the $0.0001 budget
    past_record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        input_tokens=1000,
        output_tokens=1000,
        cost_usd=1.00,
        request_id="dummy",
        tags={"key_label": "sk-test-label"},
    )
    await insert_request(initialized_db, past_record)

    # Instantiate alert engine
    from burnlens.alerts.engine import AlertEngine
    alert_engine = AlertEngine(config, initialized_db)

    # Setup transport
    transport = MockAsyncTransport({"choices": []})
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    req_body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

    # Call proxy handler
    status, headers, body, stream = await handle_request(
        client=client,
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"content-type": "application/json", "authorization": "Bearer sk-test-key"},
        body_bytes=req_body,
        query_string="",
        db_path=initialized_db,
        alert_engine=alert_engine,
        api_key_budgets=config.alerts.api_key_budgets,
        config=config,
    )
    await _flush_tasks()

    # Should return 429 and block upstream call
    assert status == 429
    assert b"exceeded" in body
    assert transport.captured_request is None  # Never made upstream request


# ---------------------------------------------------------------------------
# 5. Dashboard API Response Validation
# ---------------------------------------------------------------------------
def test_dashboard_api_returns_valid_json(tmp_path):
    """Verify local dashboard API returns correct schema structure."""
    db_path = str(tmp_path / "test_dash.db")
    config = BurnLensConfig()
    config.db_path = db_path

    app = get_app(config)
    client = TestClient(app)

    # 1. Health check
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # 2. Stats API (Summary)
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost_usd" in data
    assert "total_requests" in data

    # 3. Timeline API
    resp = client.get("/api/costs/timeline")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# 6. CLI Command Smoke Tests
# ---------------------------------------------------------------------------
def test_cli_help_smoke():
    """Verify that calling CLI help doesn't crash."""
    runner = CliRunner()
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "BurnLens" in result.output

    # check specific commands help
    result_start = runner.invoke(cli_app, ["start", "--help"])
    assert result_start.exit_code == 0
    assert "Start the BurnLens proxy server" in result_start.output
