"""OTLP span serialization from BurnLens request records."""

import hashlib
import uuid
from datetime import datetime
from typing import Any

_HEX = set("0123456789abcdef")


def _derive_trace_id(record: dict) -> str:
    """128-bit (32-hex) OTLP trace id.

    Uses the request's own ``trace_id`` when present so the exported span lands
    in the client's distributed trace: a W3C trace-id (32 hex) passes through
    verbatim, any other correlation id is hashed to a stable value. With no
    ``trace_id``, derive deterministically from ``event_id``/``request_id`` so
    re-forwarding the same event is idempotent; only a record with no id at all
    falls back to a random trace.
    """
    raw = record.get("trace_id")
    if raw:
        v = str(raw).strip().lower()
        if len(v) == 32 and set(v) <= _HEX:
            return v
        return hashlib.sha256(f"trace:{raw}".encode()).hexdigest()[:32]
    seed = record.get("event_id") or record.get("request_id")
    if seed:
        return hashlib.sha256(f"trace:{seed}".encode()).hexdigest()[:32]
    return uuid.uuid4().hex


def _derive_span_id(record: dict) -> str:
    """64-bit (16-hex) OTLP span id, stable per event for idempotent re-sync."""
    seed = record.get("event_id") or record.get("request_id")
    if seed:
        return hashlib.sha256(f"span:{seed}".encode()).hexdigest()[:16]
    return uuid.uuid4().hex[:16]


class RequestRecordToSpan:
    """Converts BurnLens RequestRecord to OpenTelemetry span format."""

    @staticmethod
    def _iso_to_unix_nano(iso_str: str) -> int:
        """Convert ISO 8601 timestamp to Unix nanoseconds."""
        try:
            if isinstance(iso_str, str):
                # Remove 'Z' suffix if present
                iso_str = iso_str.rstrip("Z")
                dt = datetime.fromisoformat(iso_str)
            else:
                dt = iso_str
            return int(dt.timestamp() * 1_000_000_000)
        except (ValueError, AttributeError):
            return int(datetime.utcnow().timestamp() * 1_000_000_000)

    @staticmethod
    def from_record(record: dict) -> dict[str, Any]:
        """
        Convert a request record to OTLP span format.

        Args:
            record: Dict with keys:
                - timestamp: ISO 8601 timestamp
                - provider: "openai" | "anthropic" | "google"
                - model: Model identifier
                - input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, cache_write_tokens
                - cost_usd: Cost in USD
                - duration_ms: Duration in milliseconds
                - status_code: HTTP status code
                - tags: Dict with optional keys: feature, team, customer

        Returns:
            Dict with OTLP span format (traceId, spanId, name, attributes, timing)
        """
        # Correlate with the client's trace / the BurnLens event instead of
        # emitting random ids (which left every exported span un-joinable).
        trace_id = _derive_trace_id(record)
        span_id = _derive_span_id(record)

        # Convert timestamps
        timestamp_iso = record.get("timestamp", datetime.utcnow().isoformat() + "Z")
        start_time_nano = RequestRecordToSpan._iso_to_unix_nano(timestamp_iso)
        duration_ms = record.get("duration_ms", 0)
        end_time_nano = start_time_nano + (duration_ms * 1_000_000)

        # Extract tags
        tags = record.get("tags", {})
        feature = tags.get("feature") if isinstance(tags, dict) else None
        team = tags.get("team") if isinstance(tags, dict) else None
        customer = tags.get("customer") if isinstance(tags, dict) else None

        # Build attributes matching burnlens/telemetry/otel.py span attributes
        attributes = {
            "llm.provider": record.get("provider", "unknown"),
            "llm.model": record.get("model", "unknown"),
            "llm.tokens.input": int(record.get("input_tokens", 0)),
            "llm.tokens.output": int(record.get("output_tokens", 0)),
            "llm.tokens.reasoning": int(record.get("reasoning_tokens", 0)),
            "llm.tokens.cache_read": int(record.get("cache_read_tokens", 0)),
            "llm.tokens.cache_write": int(record.get("cache_write_tokens", 0)),
            "llm.cost.usd": float(record.get("cost_usd", 0.0)),
            "llm.latency_ms": int(record.get("duration_ms", 0)),
            "http.status_code": int(record.get("status_code", 200)),
        }

        # Add optional BurnLens custom attributes
        if feature:
            attributes["burnlens.feature"] = feature
        if team:
            attributes["burnlens.team"] = team
        if customer:
            attributes["burnlens.customer"] = customer

        # Correlation ids: link the span back to the BurnLens cost event and the
        # provider response even when the trace/span ids are derived.
        event_id = record.get("event_id")
        if event_id:
            attributes["burnlens.event_id"] = str(event_id)
        request_id = record.get("request_id")
        if request_id:
            attributes["gen_ai.response.id"] = str(request_id)

        return {
            "traceId": trace_id,
            "spanId": span_id,
            "name": "llm.request",
            "startTimeUnixNano": start_time_nano,
            "endTimeUnixNano": end_time_nano,
            "attributes": attributes,
        }
