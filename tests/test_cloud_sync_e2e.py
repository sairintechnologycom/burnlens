"""E2E test: BurnLens proxy → cloud sync → mock ingest server.

No external dependencies — spins up a lightweight mock cloud endpoint
alongside the BurnLens proxy and verifies the full pipeline:

  SDK request → proxy logs to SQLite → sync loop pushes to cloud → cloud receives payload

Run:
  pytest tests/test_cloud_sync_e2e.py -v -s
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request, Response

from burnlens.cloud.sync import get_unsynced_count
from burnlens.config import BurnLensConfig, CloudConfig
from burnlens.storage.database import init_db

# Ports chosen to avoid conflicts with real proxy (8420) and other tests
PROXY_PORT = 18422
MOCK_CLOUD_PORT = 18423


# ---------------------------------------------------------------------------
# Mock cloud ingest server
# ---------------------------------------------------------------------------


class MockCloudServer:
    """A tiny FastAPI app that captures POST payloads from cloud sync."""

    def __init__(self) -> None:
        self.received_batches: list[dict[str, Any]] = []
        self.reject_next: bool = False
        self.app = FastAPI()

        @self.app.post("/v1/ingest")
        async def ingest(request: Request) -> Response:
            body = await request.json()
            if self.reject_next:
                self.reject_next = False
                return Response(status_code=500, content="simulated failure")
            # OSS proxy sends the API key in the X-API-Key header, not the
            # JSON body. Capture it so tests can assert on it.
            body["_api_key"] = request.headers.get("X-API-Key")
            self.received_batches.append(body)
            return Response(status_code=200, content="ok")

        @self.app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}


mock_cloud = MockCloudServer()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cloud_endpoint() -> str:
    """Start the mock cloud ingest server in a background thread."""
    server = uvicorn.Server(
        uvicorn.Config(
            mock_cloud.app,
            host="127.0.0.1",
            port=MOCK_CLOUD_PORT,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server readiness
    base = f"http://127.0.0.1:{MOCK_CLOUD_PORT}"
    for _ in range(30):
        try:
            r = httpx.get(f"{base}/health", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.2)
    else:
        pytest.fail("Mock cloud server did not start in time")

    yield base

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def e2e_config(
    tmp_path_factory: pytest.TempPathFactory,
    cloud_endpoint: str,
) -> BurnLensConfig:
    tmp = tmp_path_factory.mktemp("cloud_e2e")
    return BurnLensConfig(
        port=PROXY_PORT,
        host="127.0.0.1",
        db_path=str(tmp / "e2e.db"),
        cloud=CloudConfig(
            enabled=True,
            api_key="bl_live_e2e_test_key",
            endpoint=f"{cloud_endpoint}/v1/ingest",
            sync_interval_seconds=2,  # fast for testing
            anonymise_prompts=True,
        ),
    )


@pytest.fixture(scope="module")
def running_proxy(e2e_config: BurnLensConfig) -> str:
    """Start the BurnLens proxy with cloud sync enabled."""
    loop = asyncio.new_event_loop()
    loop.run_until_complete(init_db(e2e_config.db_path))
    loop.close()

    from burnlens.proxy.server import get_app

    app = get_app(e2e_config)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=e2e_config.host,
            port=e2e_config.port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://{e2e_config.host}:{e2e_config.port}"
    for _ in range(30):
        try:
            r = httpx.get(f"{base}/health", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.2)
    else:
        pytest.fail("BurnLens proxy did not start in time")

    yield base

    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def wait_for_unsynced_zero(db_path: str, timeout: float = 10.0) -> int:
    """Poll the un-synced count until it hits 0 or the timeout expires.

    A batch arriving at the mock cloud (received_batches growing) does NOT mean
    the DB has been marked synced — that write happens after the cloud POST
    returns 200. Asserting unsynced==0 the instant the batch shows up races that
    final write, so poll on the true completion signal instead.
    """
    deadline = time.time() + timeout
    while True:
        loop = asyncio.new_event_loop()
        unsynced = loop.run_until_complete(get_unsynced_count(db_path))
        loop.close()
        if unsynced == 0 or time.time() >= deadline:
            return unsynced
        time.sleep(0.25)


def test_proxy_request_syncs_to_cloud(
    running_proxy: str,
    e2e_config: BurnLensConfig,
) -> None:
    """Full pipeline: send request through proxy, wait for sync, verify cloud received it."""
    mock_cloud.received_batches.clear()

    # 1. Send a request through the proxy (upstream will fail — that's fine,
    #    the interceptor still logs the request to SQLite)
    try:
        httpx.post(
            f"{running_proxy}/proxy/openai/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello from e2e"}],
            },
            headers={
                "Authorization": "Bearer fake-key-for-e2e",
                "X-BurnLens-Tag-Feature": "e2e-cloud",
                "X-BurnLens-Tag-Team": "testing",
                "X-BurnLens-Tag-Customer": "acme-e2e",
            },
            timeout=15,
        )
    except Exception:
        pass  # Upstream errors expected with fake key

    # 2. Wait for the sync loop to fire (interval is 2s, give it extra time)
    deadline = time.time() + 15
    while time.time() < deadline:
        if mock_cloud.received_batches:
            break
        time.sleep(0.5)

    # 3. Verify the cloud server received the data
    assert len(mock_cloud.received_batches) > 0, (
        "Cloud endpoint received no batches within timeout"
    )

    batch = mock_cloud.received_batches[0]

    # Verify API key was sent (in the X-API-Key header, captured by the mock).
    assert batch["_api_key"] == "bl_live_e2e_test_key"

    # Verify records array
    assert len(batch["records"]) >= 1
    record = batch["records"][0]

    assert record["model"] == "gpt-4o-mini"
    assert record["provider"] == "openai"
    assert record["tag_feature"] == "e2e-cloud"
    assert record["tag_team"] == "testing"
    assert record["tag_customer"] == "acme-e2e"

    # Privacy: no raw prompt content in the payload
    payload_str = json.dumps(batch)
    assert "hello from e2e" not in payload_str
    assert "request_path" not in payload_str

    # 4. Verify records are marked as synced in the DB
    unsynced = wait_for_unsynced_zero(e2e_config.db_path)
    assert unsynced == 0, f"Expected 0 un-synced records, got {unsynced}"


def test_sync_recovers_from_cloud_failure(
    running_proxy: str,
    e2e_config: BurnLensConfig,
) -> None:
    """Records that fail to sync are retried on the next cycle."""
    initial_batch_count = len(mock_cloud.received_batches)

    # Tell the mock to reject the next request
    mock_cloud.reject_next = True

    # Send another request through the proxy
    try:
        httpx.post(
            f"{running_proxy}/proxy/openai/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "retry test"}],
            },
            headers={
                "Authorization": "Bearer fake-key",
                "X-BurnLens-Tag-Feature": "retry-test",
            },
            timeout=15,
        )
    except Exception:
        pass

    # Wait for the rejected sync attempt + a successful retry
    # (reject_next only blocks one attempt, then next cycle succeeds)
    deadline = time.time() + 15
    while time.time() < deadline:
        if len(mock_cloud.received_batches) > initial_batch_count:
            break
        time.sleep(0.5)

    # The record should eventually arrive after retry
    assert len(mock_cloud.received_batches) > initial_batch_count, (
        "Cloud endpoint did not receive retried batch"
    )

    # All records should be synced
    unsynced = wait_for_unsynced_zero(e2e_config.db_path)
    assert unsynced == 0, f"Expected 0 un-synced after retry, got {unsynced}"


def test_privacy_no_prompt_content_in_any_batch() -> None:
    """Scan all batches received by the mock cloud — none should contain prompt text."""
    for i, batch in enumerate(mock_cloud.received_batches):
        payload_str = json.dumps(batch)
        # These are the prompt contents from our test requests
        assert "hello from e2e" not in payload_str, f"Batch {i} leaks prompt content"
        assert "retry test" not in payload_str, f"Batch {i} leaks prompt content"
        # request_path could leak endpoint info and must be stripped. token
        # counts / status_code / duration are intentional operational metadata
        # (see SYNC_ALLOWED_FIELDS), not privacy-sensitive.
        for field in ["request_path"]:
            for record in batch.get("records", []):
                assert field not in record, f"Batch {i} record contains '{field}'"
