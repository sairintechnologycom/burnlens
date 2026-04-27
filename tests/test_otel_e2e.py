"""E2E test: BurnLens proxy → OTEL span → Jaeger.

Prerequisites:
  docker run -d --name jaeger-burnlens -p 4317:4317 -p 16686:16686 jaegertracing/all-in-one:latest

Run:
  pytest tests/test_otel_e2e.py -v -s
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import uvicorn

from burnlens.config import BurnLensConfig, TelemetryConfig
from burnlens.storage.database import init_db
from burnlens.telemetry.otel import init_tracer

JAEGER_QUERY = "http://localhost:16686"
OTEL_ENDPOINT = "http://localhost:4317"
PROXY_PORT = 18421  # non-default to avoid conflicts


def _jaeger_reachable() -> bool:
    try:
        r = httpx.get(f"{JAEGER_QUERY}/api/services", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _jaeger_reachable(),
    reason="Jaeger not running on localhost:16686",
)


@pytest.fixture(scope="module")
def e2e_config(tmp_path_factory: pytest.TempPathFactory) -> BurnLensConfig:
    tmp = tmp_path_factory.mktemp("otel_e2e")
    return BurnLensConfig(
        port=PROXY_PORT,
        host="127.0.0.1",
        db_path=str(tmp / "e2e.db"),
        telemetry=TelemetryConfig(
            enabled=True,
            otel_endpoint=OTEL_ENDPOINT,
            service_name="burnlens-e2e-test",
        ),
    )


@pytest.fixture(scope="module")
def running_proxy(e2e_config: BurnLensConfig):
    """Start the BurnLens proxy in a background thread."""
    import threading

    # Init DB synchronously
    asyncio.get_event_loop_policy().new_event_loop()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(init_db(e2e_config.db_path))
    loop.close()

    # Init OTEL tracer
    init_tracer(
        endpoint=e2e_config.telemetry.otel_endpoint,
        service_name=e2e_config.telemetry.service_name,
    )

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

    # Wait for server to be ready
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


def test_span_arrives_in_jaeger(running_proxy: str) -> None:
    """Send a request through the proxy and verify the span shows up in Jaeger."""
    # Send a request through the proxy (will fail upstream — that's fine,
    # the interceptor still logs and emits a span for error responses).
    try:
        httpx.post(
            f"{running_proxy}/proxy/openai/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={
                "Authorization": "Bearer fake-key-for-e2e",
                "X-BurnLens-Tag-Feature": "e2e-test",
                "X-BurnLens-Tag-Team": "testing",
                "X-BurnLens-Tag-Customer": "e2e-customer",
            },
            timeout=15,
        )
    except Exception:
        pass  # Upstream errors are expected — we just need the span

    # Force-flush the BatchSpanProcessor so spans are exported immediately
    from burnlens.telemetry.otel import flush
    flush(timeout_ms=5000)
    time.sleep(2)  # Give Jaeger a moment to index

    # Query Jaeger for our service
    resp = httpx.get(
        f"{JAEGER_QUERY}/api/traces",
        params={
            "service": "burnlens-e2e-test",
            "limit": 10,
            "lookback": "1h",
        },
        timeout=10,
    )
    assert resp.status_code == 200, f"Jaeger query failed: {resp.status_code}"

    data = resp.json()
    traces = data.get("data", [])
    assert len(traces) > 0, "No traces found in Jaeger for burnlens-e2e-test"

    # Find our span
    span_found = False
    for trace in traces:
        for span in trace.get("spans", []):
            if span.get("operationName") == "llm.request":
                span_found = True
                # Verify attributes exist
                tags = {t["key"]: t["value"] for t in span.get("tags", [])}
                assert tags.get("llm.model") == "gpt-4o-mini", f"Expected gpt-4o-mini, got {tags}"
                assert tags.get("llm.provider") == "openai"
                assert tags.get("burnlens.feature") == "e2e-test"
                assert tags.get("burnlens.team") == "testing"
                assert tags.get("burnlens.customer") == "e2e-customer"
                break
        if span_found:
            break

    assert span_found, f"No llm.request span found. Traces: {traces}"
