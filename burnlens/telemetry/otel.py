"""OpenTelemetry span export for BurnLens request records.

Requires the ``otel`` extra: ``pip install burnlens[otel]``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from burnlens.storage.models import RequestRecord, GenAICostEvent

logger = logging.getLogger(__name__)

# Lazy-loaded OTEL objects — None until init_tracer() succeeds.
_tracer: Any = None
_meter: Any = None
_request_counter: Any = None
_token_counter: Any = None
_latency_histogram: Any = None
_cost_counter: Any = None
_ttft_histogram: Any = None


def _otel_available() -> bool:
    """Return True if the opentelemetry SDK is importable."""
    try:
        import opentelemetry.sdk.trace  # noqa: F401
        return True
    except ImportError:
        return False


def init_tracer(
    endpoint: str = "http://localhost:4317",
    service_name: str = "burnlens",
) -> None:
    """Initialise the global OTEL tracer with an OTLP/gRPC exporter.

    Raises ``ImportError`` if the ``otel`` extra is not installed.
    """
    global _tracer, _meter, _request_counter, _token_counter, _latency_histogram, _cost_counter, _ttft_histogram

    from opentelemetry import trace, metrics
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    resource = Resource.create({"service.name": service_name})
    
    # Tracer setup
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("burnlens")
    
    # Meter setup
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

    logger.info("OpenTelemetry tracer and metrics initialised → %s", endpoint)


def emit_span(record: RequestRecord) -> None:
    """Create a finished span from a RequestRecord.

    If the tracer has not been initialised (or OTEL is not installed), this
    function silently does nothing — it must never break the proxy.
    """
    if _tracer is None:
        return

    try:
        span = _tracer.start_span("llm.request")
        span.set_attribute("llm.provider", record.provider)
        span.set_attribute("llm.model", record.model)
        span.set_attribute("llm.tokens.input", record.input_tokens)
        span.set_attribute("llm.tokens.output", record.output_tokens)
        span.set_attribute("llm.tokens.reasoning", record.reasoning_tokens)
        span.set_attribute("llm.cost.usd", record.cost_usd)
        span.set_attribute("llm.latency_ms", record.duration_ms)
        span.set_attribute("http.status_code", record.status_code)

        # BurnLens-specific tags
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


def emit_metrics(event: GenAICostEvent) -> None:
    """Emit metrics from a GenAICostEvent.

    If telemetry has not been initialised, this is a silent no-op.
    """
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
            attrs["burnlens.customer"] = event.customer_hash

        _request_counter.add(1, attrs)
        _latency_histogram.record(event.duration_ms, attrs)
        _cost_counter.add(event.cost_usd, attrs)

        if event.ttft_ms is not None:
            _ttft_histogram.record(event.ttft_ms, attrs)

        if event.usage:
            _token_counter.add(event.usage.input_tokens, {**attrs, "token_type": "input"})
            _token_counter.add(event.usage.output_tokens, {**attrs, "token_type": "output"})
            _token_counter.add(event.usage.reasoning_tokens, {**attrs, "token_type": "reasoning"})
    except Exception as exc:
        logger.debug("Failed to emit OTEL metrics: %s", exc)


def flush(timeout_ms: int = 5000) -> None:
    """Force-flush any pending spans. Useful for tests and graceful shutdown."""
    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout_ms)
    except Exception:
        pass


def check_otel_connection(endpoint: str = "http://localhost:4317") -> bool:
    """Try to reach the OTEL collector endpoint. Returns True on success."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 4317

    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        return True
    except OSError:
        return False
