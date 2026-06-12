# OpenTelemetry GenAI Compatibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make BurnLens enterprise-ready by fully aligning telemetry with OpenTelemetry GenAI semantic conventions, introducing OTLP metrics, measuring Time-to-First-Token (TTFT) for streaming responses, and enabling trace propagation via standard `traceparent` headers.

**Architecture:** 
1. **Model & Schema Enhancement:** Add `ttft_ms` to `RequestRecord` and `GenAICostEvent` as an optional float. Run a database migration to add the `ttft_ms` column to SQLite requests table.
2. **Streaming TTFT Capture:** In the streaming response loop, calculate the elapsed time when the first chunk is received from the upstream provider and store it as `ttft_ms`.
3. **OTLP Metrics Exporting:** Set up `MeterProvider` alongside the tracer. Define counters for request count (`llm.requests`), token usage (`llm.tokens`), cost (`llm.cost`), and histograms for latency (`llm.latency`) and TTFT (`llm.ttft`).
4. **Trace Propagation:** Extract parent trace context from incoming `traceparent` HTTP headers using OTel's `TraceContextTextMapPropagator` and start the LLM span as a child of that context.

**Tech Stack:** Python 3.11+, OpenTelemetry API & SDK (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`), aiosqlite, FastAPI, pytest.

---

### Task 1: Update Models and Database Schema with `ttft_ms`

Add the `ttft_ms` field to both `RequestRecord` and `GenAICostEvent` data classes and implement the database migration to support it.

**Files:**
- Modify: `burnlens/storage/models.py`
- Modify: `burnlens/storage/database.py`
- Test: `tests/test_phase3_models.py`

**Step 1: Write the failing test**

Create `tests/test_phase3_models.py`:
```python
import pytest
from datetime import datetime, timezone
from burnlens.storage.models import RequestRecord, GenAICostEvent, TokenUsageEvent
from burnlens.storage.database import init_db, insert_request, aiosqlite

@pytest.mark.asyncio
async def test_ttft_field_in_models_and_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    
    # 1. Test model instantiation and mapping
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        ttft_ms=120.5
    )
    
    assert record.ttft_ms == 120.5
    event = record.to_event()
    assert event.ttft_ms == 120.5
    
    record2 = RequestRecord.from_event(event)
    assert record2.ttft_ms == 120.5

    # 2. Test database migration and persistence
    await init_db(db_path)
    
    # Verify the ttft_ms column exists in the requests table
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert "ttft_ms" in columns

    # Insert request and read it back
    row_id = await insert_request(db_path, record)
    assert row_id > 0
    
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
        assert row["ttft_ms"] == 120.5
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_phase3_models.py`
Expected: FAIL (TypeError: RequestRecord() got an unexpected keyword argument 'ttft_ms')

**Step 3: Write minimal implementation**

1. Modify `burnlens/storage/models.py` to add `ttft_ms` to `GenAICostEvent` and `RequestRecord`:
```python
@dataclass
class GenAICostEvent:
    ...
    pricing_version: str | None
    ttft_ms: float | None = None
```
And:
```python
@dataclass
class RequestRecord:
    ...
    pricing_version: str | None = None
    ttft_ms: float | None = None
```
Update `to_event` and `from_event` in `RequestRecord` to copy `ttft_ms`.

2. Modify `burnlens/storage/database.py`:
- In `_CREATE_REQUESTS_TABLE`, add `ttft_ms REAL` to the columns definition.
- Create `migrate_add_ttft_column(db_path: str)`:
```python
async def migrate_add_ttft_column(db_path: str) -> None:
    """Add ``ttft_ms`` column to requests table.
    
    Safe to call multiple times -- uses PRAGMA table_info to check columns.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "ttft_ms" not in columns:
            await db.execute("ALTER TABLE requests ADD COLUMN ttft_ms REAL")
            await db.commit()
            logger.info("Migration: added ttft_ms column to requests table")
```
- Call `await migrate_add_ttft_column(db_path)` in `init_db(db_path)`.
- Update `insert_request` SQL statement and tuples to include `ttft_ms`:
```python
            INSERT OR IGNORE INTO requests (
                ...,
                ttft_ms
            ) VALUES (..., ?)
```
And add `record.ttft_ms` to the parameter tuple.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_phase3_models.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/storage/models.py burnlens/storage/database.py tests/test_phase3_models.py
git commit -m "feat(telemetry): add ttft_ms column and model fields"
```

---

### Task 2: Capture TTFT in Streaming Requests

Calculate Time-To-First-Token (TTFT) in the SSE streaming generator and record it on the RequestRecord.

**Files:**
- Modify: `burnlens/proxy/interceptor.py`
- Test: `tests/test_phase3_streaming_ttft.py`

**Step 1: Write the failing test**

Create `tests/test_phase3_streaming_ttft.py`:
```python
import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from burnlens.proxy.interceptor import handle_request
from burnlens.providers.base import Provider

@pytest.mark.asyncio
async def test_streaming_ttft_capture(tmp_path):
    db_path = str(tmp_path / "test.db")
    from burnlens.storage.database import init_db
    await init_db(db_path)

    # Mock provider
    provider = MagicMock(spec=Provider)
    provider.name = "openai"
    provider.upstream_base = "https://api.openai.com"
    provider.rewrite_path_for_routing.side_effect = lambda path, model: path

    # Mock client and response
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "text/event-stream"})
    
    # Simulated stream content yielding chunks with delay
    async def mock_aiter_bytes():
        await asyncio.sleep(0.05)  # Simulate 50ms network delay before first token
        yield b'data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1677652288, "model": "gpt-4o", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello"}, "finish_reason": null}]}'
        yield b'\n\ndata: [DONE]\n\n'

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_client.send.return_value = mock_response

    # Mock logging so we can inspect the generated RequestRecord
    records = []
    async def mock_log_record(db, record):
        records.append(record)

    with patch("burnlens.proxy.interceptor._log_record", mock_log_record):
        status, headers, body, stream = await handle_request(
            client=mock_client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"Authorization": "Bearer sk-key"},
            body_bytes=b'{"model": "gpt-4o", "stream": true}',
            query_string="",
            db_path=db_path
        )
        
        # Consume the stream to trigger logging
        assert stream is not None
        async for _ in stream:
            pass

    # Verify that record was generated and ttft_ms is positive (> 40ms due to simulated sleep)
    assert len(records) == 1
    assert records[0].ttft_ms is not None
    assert records[0].ttft_ms >= 40.0
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_phase3_streaming_ttft.py`
Expected: FAIL (AssertionError: assert None is not None)

**Step 3: Write minimal implementation**

In `burnlens/proxy/interceptor.py`:
Modify `_handle_streaming`'s `_stream_generator()` to measure the time of the first chunk:
```python
    async def _stream_generator() -> AsyncIterator[bytes]:
        raw_buffer = ""
        first_chunk_received = False
        ttft_ms = None
        try:
            async for chunk in response.aiter_bytes():
                if not first_chunk_received:
                    first_chunk_received = True
                    ttft_ms = int((time.monotonic() - start_ms) * 1000)
                yield chunk
                raw_buffer += chunk.decode("utf-8", errors="ignore")
        finally:
            duration_ref[0] = int((time.monotonic() - start_ms) * 1000)
            await response.aclose()
            usage_events = split_sse_events(raw_buffer)
            asyncio.create_task(
                _log_streaming_usage(
                    ...,
                    ttft_ms=ttft_ms,
                    ...
                )
            )
```
Update `_log_streaming_usage`'s signature to accept `ttft_ms: float | None = None` and set it on the constructed `RequestRecord`:
```python
    record = RequestRecord(
        ...
        ttft_ms=ttft_ms,
        ...
    )
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_phase3_streaming_ttft.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/proxy/interceptor.py tests/test_phase3_streaming_ttft.py
git commit -m "feat(telemetry): measure and log ttft in streaming responses"
```

---

### Task 3: Implement OpenTelemetry Metrics Exporter

Extend `burnlens/telemetry/otel.py` to initialize a global `MeterProvider` and define standard GenAI metrics:
- `llm.requests` (Counter) - tracks request count
- `llm.tokens` (Counter) - tracks token counts (differentiated by `token_type` attribute: `input` / `output` / `reasoning`)
- `llm.latency` (Histogram) - tracks latencies in ms
- `llm.cost` (Counter) - tracks total cost in USD
- `llm.ttft` (Histogram) - tracks Time-To-First-Token in ms

**Files:**
- Modify: `burnlens/telemetry/otel.py`
- Test: `tests/test_otel_metrics.py`

**Step 1: Write the failing test**

Create `tests/test_otel_metrics.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from burnlens.storage.models import RequestRecord

def _sample_event():
    return RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet",
        request_path="/v1/messages",
        input_tokens=150,
        output_tokens=75,
        reasoning_tokens=10,
        cost_usd=0.0015,
        duration_ms=450,
        ttft_ms=180.0,
        tags={"feature": "agent", "team": "devops", "customer": "acme-corp"},
        status_code=200
    ).to_event()

class TestOtelMetrics:
    """Test emit_metrics records correct values and attributes."""

    def test_metrics_recorded_successfully(self) -> None:
        from burnlens.telemetry import otel

        mock_req = MagicMock()
        mock_tok = MagicMock()
        mock_lat = MagicMock()
        mock_cost = MagicMock()
        mock_ttft = MagicMock()

        original_meter = otel._meter
        original_req = otel._request_counter
        original_tok = otel._token_counter
        original_lat = otel._latency_histogram
        original_cost = otel._cost_counter
        original_ttft = otel._ttft_histogram

        try:
            otel._meter = MagicMock()
            otel._request_counter = mock_req
            otel._token_counter = mock_tok
            otel._latency_histogram = mock_lat
            otel._cost_counter = mock_cost
            otel._ttft_histogram = mock_ttft

            event = _sample_event()
            otel.emit_metrics(event)

            # Assert request count
            mock_req.add.assert_called_once()
            val, attrs = mock_req.add.call_args[0]
            assert val == 1
            assert attrs["llm.provider"] == "anthropic"
            assert attrs["llm.model"] == "claude-3-5-sonnet"
            assert attrs["http.status_code"] == 200
            assert attrs["burnlens.feature"] == "agent"
            assert attrs["burnlens.team"] == "devops"
            assert attrs["burnlens.customer"] == "acme-corp"

            # Assert tokens
            assert mock_tok.add.call_count == 3
            tok_calls = {c[0][1]["token_type"]: c[0][0] for c in mock_tok.add.call_args_list}
            assert tok_calls["input"] == 150
            assert tok_calls["output"] == 75
            assert tok_calls["reasoning"] == 10

            # Assert latency
            mock_lat.record.assert_called_once_with(450, attrs)

            # Assert cost
            mock_cost.add.assert_called_once_with(0.0015, attrs)

            # Assert TTFT
            mock_ttft.record.assert_called_once_with(180.0, attrs)
        finally:
            otel._meter = original_meter
            otel._request_counter = original_req
            otel._token_counter = original_tok
            otel._latency_histogram = original_lat
            otel._cost_counter = original_cost
            otel._ttft_histogram = original_ttft
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_otel_metrics.py`
Expected: FAIL (AttributeError: module 'burnlens.telemetry.otel' has no attribute 'emit_metrics')

**Step 3: Write minimal implementation**

In `burnlens/telemetry/otel.py`:
1. Add lazy-loaded metric objects:
```python
_meter: Any = None
_request_counter: Any = None
_token_counter: Any = None
_latency_histogram: Any = None
_cost_counter: Any = None
_ttft_histogram: Any = None
```
2. Update `init_tracer(...)` to also initialize OTLP Metrics Exporter:
```python
def init_tracer(
    endpoint: str = "http://localhost:4317",
    service_name: str = "burnlens",
) -> None:
    # Existing tracing initialization...
    
    # Initialize OpenTelemetry Metrics
    global _meter, _request_counter, _token_counter, _latency_histogram, _cost_counter, _ttft_histogram
    
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True)
    )
    meter_provider = MeterProvider(metric_readers=[metric_reader], resource=resource)
    metrics.set_meter_provider(meter_provider)
    
    _meter = metrics.get_meter("burnlens")
    _request_counter = _meter.create_counter(
        "llm.requests", description="Number of LLM requests made"
    )
    _token_counter = _meter.create_counter(
        "llm.tokens", description="Total count of tokens processed"
    )
    _latency_histogram = _meter.create_histogram(
        "llm.latency", unit="ms", description="Latency of LLM requests"
    )
    _cost_counter = _meter.create_counter(
        "llm.cost", unit="USD", description="Cost in USD of LLM requests"
    )
    _ttft_histogram = _meter.create_histogram(
        "llm.ttft", unit="ms", description="Time to first token of LLM requests"
    )
```
3. Implement `emit_metrics(event: GenAICostEvent) -> None`:
```python
def emit_metrics(event: GenAICostEvent) -> None:
    if _meter is None:
        return
    try:
        attrs = {
            "llm.provider": event.provider,
            "llm.model": event.model,
            "http.status_code": event.status_code,
        }
        if event.team:
            attrs["burnlens.team"] = event.team
        if event.feature:
            attrs["burnlens.feature"] = event.feature
        if event.customer_hash:
            attrs["burnlens.customer"] = event.customer_hash  # fallback/anonymized customer key
            
        _request_counter.add(1, attrs)
        _latency_histogram.record(event.duration_ms, attrs)
        _cost_counter.add(event.cost_usd, attrs)
        
        if event.ttft_ms is not None:
            _ttft_histogram.record(event.ttft_ms, attrs)
            
        _token_counter.add(event.usage.input_tokens, {**attrs, "token_type": "input"})
        _token_counter.add(event.usage.output_tokens, {**attrs, "token_type": "output"})
        _token_counter.add(event.usage.reasoning_tokens, {**attrs, "token_type": "reasoning"})
    except Exception as exc:
        logger.debug("Failed to emit OTEL metrics: %s", exc)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_otel_metrics.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/telemetry/otel.py tests/test_otel_metrics.py
git commit -m "feat(telemetry): implement OTLP metrics exporter"
```

---

### Task 4: Trace Propagation via `traceparent` headers

Extract the parent trace context from incoming `traceparent` headers, linking the proxy's LLM span to the parent span.

**Files:**
- Modify: `burnlens/telemetry/otel.py`
- Test: `tests/test_otel_propagation.py`

**Step 1: Write the failing test**

Create `tests/test_otel_propagation.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from burnlens.telemetry import otel
from burnlens.storage.models import RequestRecord

def _sample_record():
    return RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions"
    )

class TestOtelPropagation:
    def test_trace_propagation_with_traceparent(self) -> None:
        """If a traceparent header is provided, the span should be a child of that trace context."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = otel._tracer
        try:
            otel._tracer = mock_tracer
            
            # Standard W3C Trace Context traceparent: version-trace_id-parent_span_id-trace_flags
            headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
            
            otel.emit_span(_sample_record(), headers=headers)

            # Assert start_span was called with correct context
            mock_tracer.start_span.assert_called_once()
            args, kwargs = mock_tracer.start_span.call_args
            assert "context" in kwargs
            context = kwargs["context"]
            
            # Retrieve span context from context
            from opentelemetry.trace import get_current_span
            parent_span = get_current_span(context)
            span_context = parent_span.get_span_context()
            
            assert f"{span_context.trace_id:032x}" == "4bf92f3577b34da6a3ce929d0e0e4736"
            assert f"{span_context.span_id:16x}" == "00f067aa0ba902b7"
        finally:
            otel._tracer = original
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_otel_propagation.py`
Expected: FAIL (TypeError: emit_span() got an unexpected keyword argument 'headers')

**Step 3: Write minimal implementation**

In `burnlens/telemetry/otel.py`:
Update `emit_span` to accept `headers` and use OpenTelemetry's `TraceContextTextMapPropagator` to extract parent context:
```python
def emit_span(record: RequestRecord, headers: dict[str, str] | None = None) -> None:
    if _tracer is None:
        return

    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        
        parent_context = None
        if headers:
            try:
                # Extract context from incoming carrier headers (case-insensitive keys)
                parent_context = TraceContextTextMapPropagator().extract(carrier=headers)
            except Exception:
                pass

        span = _tracer.start_span("llm.request", context=parent_context)
        
        # Add attributes...
        span.set_attribute("llm.provider", record.provider)
        span.set_attribute("llm.model", record.model)
        span.set_attribute("llm.tokens.input", record.input_tokens)
        span.set_attribute("llm.tokens.output", record.output_tokens)
        span.set_attribute("llm.tokens.reasoning", record.reasoning_tokens)
        span.set_attribute("llm.cost.usd", record.cost_usd)
        span.set_attribute("llm.latency_ms", record.duration_ms)
        span.set_attribute("http.status_code", record.status_code)
        if record.ttft_ms is not None:
            span.set_attribute("llm.ttft_ms", record.ttft_ms)

        # BurnLens specific attributes
        tags = record.tags or {}
        if "feature" in tags:
            span.set_attribute("burnlens.feature", tags["feature"])
        if "team" in tags:
            span.set_attribute("burnlens.team", tags["team"])
        if "customer" in tags:
            span.set_attribute("burnlens.customer", tags["customer"])

        span.end()
    except Exception as exc:
        logger.debug("Failed to emit OTEL span: %s", exc)
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_otel_propagation.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/telemetry/otel.py tests/test_otel_propagation.py
git commit -m "feat(telemetry): support trace propagation via traceparent headers"
```

---

### Task 5: Integrate Telemetry in Interceptor Flow

Incorporate the new metrics emitting alongside span emitting immediately in the request interception handlers.

**Files:**
- Modify: `burnlens/proxy/interceptor.py`
- Test: Run entire suite (`.venv/bin/pytest tests/test_otel.py tests/test_otel_metrics.py tests/test_otel_propagation.py`)

**Step 1: Write the failing test**

There's no new failing test needed as this integration is covered by ensuring all existing and newly added tests pass successfully under venv.

**Step 2: Write implementation**

In `burnlens/proxy/interceptor.py`:
1. In `_handle_non_streaming`, call `emit_span` immediately after building the `RequestRecord`, passing `original_headers or headers`:
```python
    record = RequestRecord(...)
    
    # Emit OTEL span and metrics immediately
    try:
        from burnlens.telemetry.otel import emit_span, emit_metrics
        emit_span(record, original_headers or headers)
        emit_metrics(record.to_event())
    except Exception as exc:
        logger.debug("OTEL telemetry emit failed: %s", exc)
```

2. In `_log_streaming_usage`, call `emit_span` and `emit_metrics` after building the streaming `RequestRecord`:
```python
    record = RequestRecord(...)
    
    # Emit OTEL span and metrics immediately
    try:
        from burnlens.telemetry.otel import emit_span, emit_metrics
        emit_span(record, meta)  # meta acts as carrier containing traceparent header if available
        emit_metrics(record.to_event())
    except Exception as exc:
        logger.debug("OTEL telemetry emit failed: %s", exc)
```

3. Ensure we clean up any duplicate or outdated calls to `emit_span` (e.g. inside `_log_record`, remove the nested try/except block that calls `emit_span(record)` to avoid double-exporting spans).

**Step 3: Run full verification suite**

Run: `.venv/bin/pytest tests/test_otel.py tests/test_otel_metrics.py tests/test_otel_propagation.py`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add burnlens/proxy/interceptor.py
git commit -m "feat(telemetry): trigger span and metrics emission directly in interceptor"
```
