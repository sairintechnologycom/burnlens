"""OTLP span serialization from BurnLens request records."""

import uuid
from datetime import datetime
from typing import Any


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
        # Generate trace and span IDs (random for now)
        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]

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

        return {
            "traceId": trace_id,
            "spanId": span_id,
            "name": "llm.request",
            "startTimeUnixNano": start_time_nano,
            "endTimeUnixNano": end_time_nano,
            "attributes": attributes,
        }
