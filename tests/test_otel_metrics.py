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
            assert attrs["gen_ai.system"] == "anthropic"
            assert attrs["gen_ai.request.model"] == "claude-3-5-sonnet"
            assert attrs["llm.provider"] == "anthropic"
            assert attrs["llm.model"] == "claude-3-5-sonnet"
            assert attrs["http.status_code"] == 200
            assert attrs["burnlens.feature"] == "agent"
            assert attrs["burnlens.team"] == "devops"
            import hashlib
            assert attrs["burnlens.customer"] == hashlib.sha256(b"acme-corp").hexdigest()

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

    def test_otel_disabled_no_metrics(self) -> None:
        """When meter is not initialised, emit_metrics is a silent no-op."""
        from burnlens.telemetry import otel

        original = otel._meter
        try:
            otel._meter = None
            # Should not raise
            otel.emit_metrics(_sample_event())
        finally:
            otel._meter = original
