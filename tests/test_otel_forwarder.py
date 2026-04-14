"""Tests for OpenTelemetry span forwarding."""

import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from burnlens_cloud.telemetry.forwarder import OtelForwarder
from burnlens_cloud.telemetry.otel_proto import RequestRecordToSpan
from burnlens_cloud.encryption import EncryptionManager


@pytest.fixture
def sample_record():
    """Sample request record for testing."""
    return {
        "timestamp": "2025-01-01T12:00:00Z",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 100,
        "output_tokens": 50,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.00075,
        "duration_ms": 320,
        "status_code": 200,
        "tags": {"feature": "chat", "team": "backend", "customer": "acme"},
    }


@pytest.fixture
def forwarder():
    """Create forwarder instance."""
    return OtelForwarder(timeout_seconds=5)


class TestOtelProtoConversion:
    """Test conversion of request records to OTLP spans."""

    def test_record_to_span_has_all_attributes(self, sample_record):
        """Span should contain all required LLM attributes."""
        span = RequestRecordToSpan.from_record(sample_record)

        assert span["name"] == "llm.request"
        assert span["traceId"]  # UUID hex string
        assert span["spanId"]  # Partial UUID
        assert "attributes" in span
        assert "startTimeUnixNano" in span
        assert "endTimeUnixNano" in span

    def test_span_attributes_include_llm_data(self, sample_record):
        """Span attributes should include all LLM metrics."""
        span = RequestRecordToSpan.from_record(sample_record)
        attrs = span["attributes"]

        assert attrs["llm.provider"] == "openai"
        assert attrs["llm.model"] == "gpt-4o-mini"
        assert attrs["llm.tokens.input"] == 100
        assert attrs["llm.tokens.output"] == 50
        assert attrs["llm.tokens.reasoning"] == 0
        assert attrs["llm.cost.usd"] == 0.00075
        assert attrs["llm.latency_ms"] == 320
        assert attrs["http.status_code"] == 200

    def test_span_attributes_include_burnlens_tags(self, sample_record):
        """Span should include custom BurnLens tag attributes."""
        span = RequestRecordToSpan.from_record(sample_record)
        attrs = span["attributes"]

        assert attrs["burnlens.feature"] == "chat"
        assert attrs["burnlens.team"] == "backend"
        assert attrs["burnlens.customer"] == "acme"

    def test_span_timing_calculated_correctly(self, sample_record):
        """Span should have correct timing (start + duration)."""
        span = RequestRecordToSpan.from_record(sample_record)

        start_nano = span["startTimeUnixNano"]
        end_nano = span["endTimeUnixNano"]

        # Duration should be 320ms = 320,000,000 nanoseconds
        duration_nano = end_nano - start_nano
        assert duration_nano == 320_000_000

    def test_record_with_empty_tags(self):
        """Record without tags should not include burnlens attributes."""
        record = {
            "timestamp": "2025-01-01T12:00:00Z",
            "provider": "anthropic",
            "model": "claude-3.5-sonnet",
            "input_tokens": 50,
            "output_tokens": 25,
            "cost_usd": 0.0005,
            "duration_ms": 200,
            "status_code": 200,
            "tags": {},
        }
        span = RequestRecordToSpan.from_record(record)
        attrs = span["attributes"]

        assert "burnlens.feature" not in attrs
        assert "burnlens.team" not in attrs
        assert "burnlens.customer" not in attrs


class TestOtelForwarder:
    """Test OTEL forwarder functionality."""

    @pytest.mark.asyncio
    async def test_forward_batch_success(self, forwarder, sample_record):
        """Successful forward should return True."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await forwarder.forward_batch(
                [sample_record],
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward_batch_failure_non_2xx(self, forwarder, sample_record):
        """Non-2xx response should return False."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 400

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await forwarder.forward_batch(
                [sample_record],
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_forward_batch_timeout_handled(self, forwarder, sample_record):
        """Timeout should return False without raising."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Timeout")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await forwarder.forward_batch(
                [sample_record],
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_forward_batch_empty_records(self, forwarder):
        """Empty record list should return True (no-op)."""
        result = await forwarder.forward_batch(
            [],
            "https://otel.example.com/v1/traces",
            "Bearer sk_test_123",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_forward_batch_payload_structure(self, forwarder, sample_record):
        """Forwarded payload should match OTLP JSON structure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await forwarder.forward_batch(
                [sample_record],
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            # Verify payload structure
            call_kwargs = mock_client.post.call_args[1]
            payload = call_kwargs["json"]

            assert "resourceSpans" in payload
            assert len(payload["resourceSpans"]) == 1
            assert "scopeSpans" in payload["resourceSpans"][0]
            assert len(payload["resourceSpans"][0]["scopeSpans"]) == 1
            assert "spans" in payload["resourceSpans"][0]["scopeSpans"][0]

    @pytest.mark.asyncio
    async def test_test_endpoint_success(self, forwarder):
        """Test endpoint should return (True, latency_ms)."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            ok, latency_ms = await forwarder.test_endpoint(
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            assert ok is True
            assert isinstance(latency_ms, int)
            assert latency_ms >= 0

    @pytest.mark.asyncio
    async def test_test_endpoint_failure(self, forwarder):
        """Test endpoint failure should return (False, latency_ms)."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 500

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            ok, latency_ms = await forwarder.test_endpoint(
                "https://otel.example.com/v1/traces",
                "Bearer sk_test_123",
            )

            assert ok is False
            assert isinstance(latency_ms, int)


class TestEncryption:
    """Test encryption utilities for API keys."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypted data should be recoverable by decryption."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        manager = EncryptionManager(key)

        plaintext = "Bearer sk_test_1234567890abcdefgh"
        encrypted = manager.encrypt(plaintext)

        assert encrypted != plaintext
        decrypted = manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_mask_api_key(self):
        """API key masking should show only last 4 chars."""
        api_key = "Bearer sk_test_1234567890abcdefghijklmnop"
        masked = EncryptionManager.mask_api_key(api_key, visible_chars=4)

        assert "****" in masked
        assert "ijkl" in masked  # Last 4 visible
        assert "test" not in masked  # Middle hidden

    def test_mask_short_api_key(self):
        """Very short API keys should be masked."""
        masked = EncryptionManager.mask_api_key("abc", visible_chars=4)
        assert masked == "****"
