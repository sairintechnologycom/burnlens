"""Tests for OpenTelemetry span export."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from burnlens.storage.models import RequestRecord


def _sample_record(**overrides: object) -> RequestRecord:
    defaults = dict(
        provider="openai",
        model="gpt-4o-mini",
        request_path="/v1/chat/completions",
        timestamp=datetime(2025, 1, 1),
        input_tokens=100,
        output_tokens=50,
        reasoning_tokens=0,
        cost_usd=0.000075,
        duration_ms=320,
        status_code=200,
        tags={"feature": "chat", "team": "backend", "customer": "acme"},
    )
    defaults.update(overrides)
    return RequestRecord(**defaults)  # type: ignore[arg-type]


class TestEmitSpan:
    """Test emit_span creates correct OTEL spans."""

    def test_span_emitted_after_init(self) -> None:
        """After init_tracer, emit_span should create a span."""
        from burnlens.telemetry import otel

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = otel._tracer
        try:
            otel._tracer = mock_tracer
            otel.emit_span(_sample_record())

            mock_tracer.start_span.assert_called_once_with("llm.request")
            mock_span.end.assert_called_once()
        finally:
            otel._tracer = original

    def test_span_has_correct_attributes(self) -> None:
        """Span attributes must match the RequestRecord fields."""
        from burnlens.telemetry import otel

        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = otel._tracer
        try:
            otel._tracer = mock_tracer
            otel.emit_span(_sample_record())

            calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
            assert calls["llm.provider"] == "openai"
            assert calls["llm.model"] == "gpt-4o-mini"
            assert calls["llm.tokens.input"] == 100
            assert calls["llm.tokens.output"] == 50
            assert calls["llm.tokens.reasoning"] == 0
            assert calls["llm.cost.usd"] == 0.000075
            assert calls["llm.latency_ms"] == 320
            assert calls["http.status_code"] == 200
            assert calls["burnlens.feature"] == "chat"
            assert calls["burnlens.team"] == "backend"
            assert calls["burnlens.customer"] == "acme"
        finally:
            otel._tracer = original

    def test_otel_disabled_by_default_no_spans(self) -> None:
        """When tracer is not initialised, emit_span is a silent no-op."""
        from burnlens.telemetry import otel

        original = otel._tracer
        try:
            otel._tracer = None
            # Should not raise
            otel.emit_span(_sample_record())
        finally:
            otel._tracer = original

    def test_otel_failure_does_not_crash_proxy(self) -> None:
        """If the tracer raises, emit_span catches and doesn't propagate."""
        from burnlens.telemetry import otel

        mock_tracer = MagicMock()
        mock_tracer.start_span.side_effect = RuntimeError("exporter down")

        original = otel._tracer
        try:
            otel._tracer = mock_tracer
            # Must not raise
            otel.emit_span(_sample_record())
        finally:
            otel._tracer = original


class TestOtelConfig:
    """Test telemetry config loading."""

    def test_telemetry_defaults(self) -> None:
        from burnlens.config import BurnLensConfig
        cfg = BurnLensConfig()
        assert cfg.telemetry.enabled is False
        assert cfg.telemetry.otel_endpoint == "http://localhost:4317"
        assert cfg.telemetry.service_name == "burnlens"

    def test_telemetry_from_yaml(self, tmp_path: "pytest.TempPathFactory") -> None:
        from burnlens.config import load_config
        yaml_file = tmp_path / "burnlens.yaml"  # type: ignore[operator]
        yaml_file.write_text(
            "telemetry:\n"
            "  enabled: true\n"
            "  otel_endpoint: http://otel:4317\n"
            "  service_name: my-app\n"
        )
        cfg = load_config(str(yaml_file))
        assert cfg.telemetry.enabled is True
        assert cfg.telemetry.otel_endpoint == "http://otel:4317"
        assert cfg.telemetry.service_name == "my-app"
