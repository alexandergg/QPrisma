"""Regression tests for agent.utils.observability module."""

import pytest
from agent.utils.observability import ConversationIdSpanProcessor
from opentelemetry.sdk.trace import SpanProcessor


@pytest.mark.unit
class TestConversationIdSpanProcessor:
    """Guard against removing the SpanProcessor base class.

    Newer OpenTelemetry SDK versions require lifecycle hooks (e.g.
    ``_on_ending``) provided by ``SpanProcessor``.  Without the
    inheritance the tracer crashes at startup.  See PR #53.
    """

    def test_inherits_from_span_processor(self):
        assert issubclass(ConversationIdSpanProcessor, SpanProcessor)

    @pytest.mark.parametrize(
        "method",
        ["on_start", "on_end", "shutdown", "force_flush"],
    )
    def test_has_span_processor_interface(self, method: str):
        assert hasattr(ConversationIdSpanProcessor, method)
