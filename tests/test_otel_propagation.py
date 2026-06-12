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
            assert f"{span_context.span_id:016x}" == "00f067aa0ba902b7"
        finally:
            otel._tracer = original
