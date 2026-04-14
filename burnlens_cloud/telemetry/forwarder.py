"""OpenTelemetry span forwarder for enterprise customers."""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from .otel_proto import RequestRecordToSpan

logger = logging.getLogger(__name__)


class OtelForwarder:
    """Forwards BurnLens cost records as OTLP spans to customer's collector endpoint."""

    def __init__(self, timeout_seconds: int = 5):
        """Initialize forwarder with configurable timeout."""
        self.timeout_seconds = timeout_seconds

    async def forward_batch(
        self, records: list[dict], endpoint: str, api_key: str
    ) -> bool:
        """
        Convert RequestRecords to OTLP JSON spans and POST to customer's endpoint.

        Args:
            records: List of request record dicts with keys:
                - timestamp, provider, model, input_tokens, output_tokens,
                - reasoning_tokens, cache_read_tokens, cache_write_tokens,
                - cost_usd, duration_ms, status_code, tags (optional)
            endpoint: Customer's OTLP/HTTP endpoint (e.g., https://otel.datadoghq.com/v1/traces)
            api_key: API key for authentication (e.g., "Bearer xxx")

        Returns:
            True on successful POST (2xx), False on any failure.
            Never raises exceptions — failures logged and returned as False.
        """
        if not records:
            return True

        try:
            # Convert records to OTLP spans
            spans = []
            for record in records:
                span = RequestRecordToSpan.from_record(record)
                spans.append(span)

            # Build OTLP payload
            payload = {
                "resourceSpans": [
                    {
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "name": span["name"],
                                        "spanId": span["spanId"],
                                        "traceId": span["traceId"],
                                        "attributes": span["attributes"],
                                        "startTimeUnixNano": span["startTimeUnixNano"],
                                        "endTimeUnixNano": span["endTimeUnixNano"],
                                        "status": {"code": "UNSET"},
                                    }
                                    for span in spans
                                ]
                            }
                        ]
                    }
                ]
            }

            # POST to customer endpoint
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers={
                        "Authorization": api_key,
                        "Content-Type": "application/json",
                    },
                )

                if 200 <= response.status_code < 300:
                    logger.info(
                        f"OTEL forward successful: {len(records)} spans to {endpoint}"
                    )
                    return True
                else:
                    logger.warning(
                        f"OTEL forward failed: {response.status_code} from {endpoint}"
                    )
                    return False

        except asyncio.TimeoutError:
            logger.warning(
                f"OTEL forward timeout after {self.timeout_seconds}s to {endpoint}"
            )
            return False
        except Exception as e:
            logger.error(f"OTEL forward error: {type(e).__name__}: {e}")
            return False

    async def test_endpoint(self, endpoint: str, api_key: str) -> tuple[bool, int]:
        """
        Send a single test span to validate endpoint connectivity.

        Returns:
            (ok, latency_ms) tuple. ok=True if 2xx response.
        """
        try:
            test_record = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "provider": "test",
                "model": "test",
                "input_tokens": 1,
                "output_tokens": 1,
                "reasoning_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0.0,
                "duration_ms": 1,
                "status_code": 200,
                "tags": {},
            }

            start = time.time()
            success = await self.forward_batch([test_record], endpoint, api_key)
            latency_ms = int((time.time() - start) * 1000)

            return success, latency_ms

        except Exception as e:
            logger.error(f"OTEL test endpoint error: {e}")
            return False, 0


# Global forwarder instance
_forwarder: Optional[OtelForwarder] = None


def get_forwarder() -> OtelForwarder:
    """Get or initialize the global forwarder instance."""
    global _forwarder
    if _forwarder is None:
        _forwarder = OtelForwarder()
    return _forwarder
