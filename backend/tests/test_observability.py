"""Regression tests for agent.utils.observability module."""

from unittest.mock import MagicMock

import agent.hosted.telemetry as telemetry_mod
import pytest
from agent.utils.observability import (
    ConversationIdSpanProcessor,
    hash_identifier,
    set_conversation_id,
    set_otel_media_context,
    set_otel_user_id,
)
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

    def test_hash_identifier_is_deterministic_and_redacted(self):
        raw_value = "user-123@example.com"

        hashed = hash_identifier(raw_value)

        assert hashed == hash_identifier(raw_value)
        assert hashed is not None
        assert hashed.startswith("sha256:")
        assert raw_value not in hashed

    def test_on_start_stamps_foundry_conversation_and_hashed_qprisma_context(self):
        class FakeSpan:
            def __init__(self):
                self.attributes = {}

            def set_attribute(self, key: str, value):
                self.attributes[key] = value

        set_conversation_id("foundry-conversation-123")
        set_otel_user_id("user-123@example.com")
        set_otel_media_context(
            media_id="media-123",
            media_ids=["media-123", "media-456"],
            session_id="session-123",
        )
        span = FakeSpan()

        ConversationIdSpanProcessor().on_start(span)

        assert span.attributes["gen_ai.conversation.id"] == "foundry-conversation-123"
        assert span.attributes["enduser.id"] == hash_identifier("user-123@example.com")
        assert span.attributes["qprisma.user.id.hash"] == hash_identifier("user-123@example.com")
        assert span.attributes["qprisma.media.id.hash"] == hash_identifier("media-123")
        assert span.attributes["qprisma.media.count"] == 2
        assert span.attributes["qprisma.media.ids.hash"] == [
            hash_identifier("media-123"),
            hash_identifier("media-456"),
        ]
        assert span.attributes["qprisma.session.id.hash"] == hash_identifier("session-123")
        assert "user-123@example.com" not in span.attributes.values()

        set_conversation_id(None)
        set_otel_user_id(None)
        set_otel_media_context()


@pytest.mark.unit
class TestAzureAITracerTelemetryModule:
    """Tests for the tracer singleton in agent.hosted.telemetry."""

    def test_get_azure_ai_tracer_returns_none_by_default(self, monkeypatch: pytest.MonkeyPatch):
        """Tracer singleton is None when _setup_telemetry() hasn't run."""
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", None)

        assert telemetry_mod.get_azure_ai_tracer() is None

    def test_get_azure_ai_tracer_is_callable(self):
        """get_azure_ai_tracer() is importable and callable."""
        assert callable(telemetry_mod.get_azure_ai_tracer)

    def test_set_and_get_roundtrip(self, monkeypatch: pytest.MonkeyPatch):
        """set_azure_ai_tracer() stores the singleton for get_azure_ai_tracer()."""
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", None)

        mock_tracer = MagicMock(name="mock_azure_tracer")
        telemetry_mod.set_azure_ai_tracer(mock_tracer)
        assert telemetry_mod.get_azure_ai_tracer() is mock_tracer

    def test_set_none_clears_singleton(self, monkeypatch: pytest.MonkeyPatch):
        """set_azure_ai_tracer(None) clears a previously stored tracer."""
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", MagicMock())
        telemetry_mod.set_azure_ai_tracer(None)
        assert telemetry_mod.get_azure_ai_tracer() is None


@pytest.mark.unit
class TestCompileTimeTracerInjection:
    """Validate the refreshed-preview tracer wiring contract.

    The legacy ``QPrismaStateConverter`` injected the tracer into each request's
    ``config.callbacks``. Under the refreshed Responses preview the tracer is
    bound once at compile-time via ``graph.with_config({"callbacks": [tracer]})``
    inside :func:`agent.hosted.main._get_graph`. These tests exercise the
    shared singleton contract that ``_get_graph`` relies on, plus the
    ``with_config`` invocation shape.
    """

    def test_with_config_receives_tracer_when_available(self, monkeypatch: pytest.MonkeyPatch):
        """When tracer is set, it is passed to ``graph.with_config`` callbacks."""

        mock_tracer = MagicMock(name="mock_azure_tracer")
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", mock_tracer)
        tracer = telemetry_mod.get_azure_ai_tracer()
        assert tracer is mock_tracer

        graph = MagicMock(name="compiled_graph")
        configured = MagicMock(name="configured_graph")
        graph.with_config.return_value = configured

        callbacks = [tracer] if tracer is not None else []
        config: dict = {"tags": ["qprisma", "video-agent", "hosted"]}
        if callbacks:
            config["callbacks"] = callbacks
        result = graph.with_config(config)

        graph.with_config.assert_called_once()
        passed = graph.with_config.call_args[0][0]
        assert passed["callbacks"] == [mock_tracer]
        assert "qprisma" in passed["tags"]
        assert result is configured

    def test_with_config_omits_callbacks_when_tracer_absent(self, monkeypatch: pytest.MonkeyPatch):
        """When tracer singleton is None, no callbacks key is injected."""

        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", None)
        tracer = telemetry_mod.get_azure_ai_tracer()
        assert tracer is None

        graph = MagicMock(name="compiled_graph")
        callbacks = [tracer] if tracer is not None else []
        config: dict = {"tags": ["qprisma", "video-agent", "hosted"]}
        if callbacks:
            config["callbacks"] = callbacks
        graph.with_config(config)

        passed = graph.with_config.call_args[0][0]
        assert "callbacks" not in passed
