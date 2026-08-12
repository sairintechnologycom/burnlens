"""OpenTelemetry span forwarder for enterprise customers."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
import ipaddress
import socket

import httpx

from .otel_proto import RequestRecordToSpan

logger = logging.getLogger(__name__)


class OtelForwarder:
    """Forwards BurnLens cost records as OTLP spans to customer's collector endpoint."""

    def __init__(self, timeout_seconds: int = 5):
        """Initialize forwarder with configurable timeout."""
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _ip_is_internal(ip: ipaddress._BaseAddress) -> bool:
        """True if the IP is not a safe public destination (covers link-local
        169.254.169.254 metadata, loopback, RFC1918, multicast, reserved)."""
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    def _safe_target(self, endpoint: str) -> tuple[str, str, str] | None:
        """Resolve an OTEL endpoint to a connect target that cannot be rebound.

        Returns ``(url, host_header, sni_hostname)`` where ``url`` addresses the
        exact validated IP, or None if the endpoint is not a safe destination.

        Validating a hostname and then handing that same hostname to httpx
        leaves a DNS-rebinding window: the attacker's name passes the check on
        the first resolve and returns 169.254.169.254 on the second, which is
        the one that actually gets connected to. Pinning the address we checked
        removes the second resolve, so there is no window to win. TLS is
        unaffected — the handshake and certificate check still use the real
        hostname via SNI, so a pinned connection to a mismatched host fails.

        - Must be HTTPS.
        - Must not resolve to a private/internal/metadata IP address.
        """
        try:
            parsed = urlparse(endpoint)
            if parsed.scheme != "https":
                logger.warning(f"Invalid OTEL endpoint scheme: {parsed.scheme}. Only HTTPS allowed.")
                return None

            hostname = parsed.hostname
            if not hostname:
                return None

            port = parsed.port or 443
            host_header = hostname if port == 443 else f"{hostname}:{port}"

            # IP literal: check directly. Already an address, so nothing to pin.
            try:
                if self._ip_is_internal(ipaddress.ip_address(hostname)):
                    logger.warning(f"Blocked internal OTEL endpoint IP: {hostname}")
                    return None
                return endpoint, host_header, hostname
            except ValueError:
                pass  # Not a literal — a hostname, resolve it below.

            # Hostname: resolve and reject if ANY resolved address is internal.
            # Closes the DNS-based SSRF path (e.g. a name pointing at
            # 169.254.169.254 or 10.x). getaddrinfo blocks briefly, which is
            # fine here — forwarding already runs as a fire-and-forget task.
            try:
                infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
            except socket.gaierror as e:
                logger.warning(f"OTEL endpoint {hostname} did not resolve: {e}")
                return None

            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if self._ip_is_internal(ip):
                    logger.warning(f"Blocked OTEL endpoint {hostname} resolving to internal IP {ip}")
                    return None

            if not infos:
                return None
            pinned = ipaddress.ip_address(infos[0][4][0])
            netloc = f"[{pinned}]" if pinned.version == 6 else str(pinned)
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return parsed._replace(netloc=netloc).geturl(), host_header, hostname
        except Exception as e:
            logger.error(f"Error validating OTEL endpoint {endpoint}: {e}")
            return None

    def _validate_endpoint(self, endpoint: str) -> bool:
        """True if the endpoint is a safe forwarding destination."""
        return self._safe_target(endpoint) is not None

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

        target = self._safe_target(endpoint)
        if target is None:
            return False
        url, host_header, sni_hostname = target

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
                                        # Omitted entirely when there is no
                                        # parent: OTLP reads a present-but-empty
                                        # parentSpanId as a malformed link, not
                                        # as a root span.
                                        **(
                                            {"parentSpanId": span["parentSpanId"]}
                                            if span.get("parentSpanId")
                                            else {}
                                        ),
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
                    url,
                    json=payload,
                    headers={
                        "Authorization": api_key,
                        "Content-Type": "application/json",
                        # url points at the pinned IP, so the name the customer
                        # configured has to be carried explicitly — many
                        # collectors sit behind name-based routing.
                        "Host": host_header,
                    },
                    # Drives both SNI and certificate verification, so pinning
                    # the IP does not weaken TLS.
                    extensions={"sni_hostname": sni_hostname},
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
