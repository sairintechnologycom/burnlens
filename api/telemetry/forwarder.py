"""OTLP/HTTP span forwarder — ships cost spans to customer's collector."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

OTLP_TIMEOUT = 10  # seconds


def _make_attr(key: str, value) -> dict:
    """Build a single OTLP attribute entry."""
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _record_to_span(record: dict) -> dict:
    """Convert one ingest record dict to an OTLP span dict."""
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]

    ts_raw = record.get("ts") or record.get("timestamp")
    if isinstance(ts_raw, datetime):
        start_ns = int(ts_raw.timestamp() * 1_000_000_000)
    elif isinstance(ts_raw, str):
        dt = datetime.fromisoformat(ts_raw.rstrip("Z"))
        start_ns = int(dt.timestamp() * 1_000_000_000)
    else:
        start_ns = int(time.time() * 1_000_000_000)

    latency_ms = int(record.get("latency_ms") or record.get("duration_ms") or 0)
    end_ns = start_ns + latency_ms * 1_000_000

    attrs = [
        _make_attr("llm.provider", record.get("provider", "unknown")),
        _make_attr("llm.model", record.get("model", "unknown")),
        _make_attr("llm.tokens.input", int(record.get("input_tokens", 0))),
        _make_attr("llm.tokens.output", int(record.get("output_tokens", 0))),
        _make_attr("llm.tokens.reasoning", int(record.get("reasoning_tokens", 0))),
        _make_attr("llm.cost.usd", float(record.get("cost_usd", 0.0))),
        _make_attr("llm.latency_ms", latency_ms),
        _make_attr("http.status_code", int(record.get("status_code", 200))),
    ]

    # Optional tag-based attributes
    if record.get("tag_feature"):
        attrs.append(_make_attr("burnlens.feature", record["tag_feature"]))
    if record.get("tag_team"):
        attrs.append(_make_attr("burnlens.team", record["tag_team"]))
    if record.get("tag_customer"):
        attrs.append(_make_attr("burnlens.customer", record["tag_customer"]))

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": "llm.request",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
        "status": {"code": 1},
    }


def _build_payload(
    spans: list[dict], workspace_id: str = ""
) -> dict:
    """Build full OTLP JSON payload."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _make_attr("service.name", "burnlens"),
                        _make_attr("workspace.id", workspace_id),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "burnlens.cost"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


class OtelForwarder:
    """Forwards cost records as OTLP spans to a customer's OTLP/HTTP endpoint."""

    async def forward_batch(
        self,
        records: list[dict],
        endpoint: str,
        api_key: str,
        workspace_id: str = "",
    ) -> tuple[bool, str]:
        """
        POST spans to endpoint/v1/traces.

        Returns (True, "") on 2xx, (False, error_message) on failure.
        Never raises.
        """
        if not records:
            return True, ""

        try:
            spans = [_record_to_span(r) for r in records]
            payload = _build_payload(spans, workspace_id)

            url = endpoint.rstrip("/") + "/v1/traces"
            async with httpx.AsyncClient(timeout=OTLP_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if 200 <= resp.status_code < 300:
                logger.info("OTEL forwarded %d spans to %s", len(spans), endpoint)
                return True, ""
            msg = f"HTTP {resp.status_code} from {endpoint}"
            logger.warning("OTEL forward failed: %s", msg)
            return False, msg

        except httpx.TimeoutException:
            msg = f"Timeout after {OTLP_TIMEOUT}s to {endpoint}"
            logger.warning("OTEL forward: %s", msg)
            return False, msg
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            logger.error("OTEL forward error: %s", msg)
            return False, msg

    async def send_test_span(
        self, endpoint: str, api_key: str
    ) -> tuple[bool, int, str]:
        """
        Send one zero-value test span.

        Returns (success, latency_ms, error_message).
        """
        test_record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "provider": "test",
            "model": "burnlens-test",
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "status_code": 200,
        }
        start = time.time()
        ok, err = await self.forward_batch([test_record], endpoint, api_key)
        latency_ms = int((time.time() - start) * 1000)
        return ok, latency_ms, err


# Module-level singleton
_forwarder: OtelForwarder | None = None


def get_forwarder() -> OtelForwarder:
    global _forwarder
    if _forwarder is None:
        _forwarder = OtelForwarder()
    return _forwarder
