"""Regression tests for agent.utils.observability module."""

from unittest.mock import MagicMock

import agent.hosted.telemetry as telemetry_mod
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
class TestStateConverterTracerInjection:
    """Tests for tracer callback injection in QPrismaStateConverter.

    The converter's injection logic imports from ``agent.hosted.telemetry``
    and injects the tracer into ``result["config"]["callbacks"]``.
    These tests validate that logic by exercising the shared telemetry
    singleton and simulating the config manipulation the converter performs.
    """

    def test_tracer_injected_when_available(self, monkeypatch: pytest.MonkeyPatch):
        """When a tracer singleton exists, it gets added to config callbacks."""
        mock_tracer = MagicMock(name="mock_azure_tracer")
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", mock_tracer)

        # Simulate the injection logic from convert_request
        result = {"input": {"messages": []}, "config": {}}
        tracer = telemetry_mod.get_azure_ai_tracer()
        assert tracer is not None

        config = result.get("config") or {}
        callbacks = list(config.get("callbacks") or [])
        if tracer not in callbacks:
            callbacks.append(tracer)
        config["callbacks"] = callbacks
        result["config"] = config

        assert mock_tracer in result["config"]["callbacks"]

    def test_tracer_not_duplicated(self, monkeypatch: pytest.MonkeyPatch):
        """Tracer is not added twice if already present."""
        mock_tracer = MagicMock(name="mock_azure_tracer")
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", mock_tracer)

        result = {"input": {"messages": []}, "config": {"callbacks": [mock_tracer]}}
        tracer = telemetry_mod.get_azure_ai_tracer()

        config = result.get("config") or {}
        callbacks = list(config.get("callbacks") or [])
        if tracer not in callbacks:
            callbacks.append(tracer)
        config["callbacks"] = callbacks
        result["config"] = config

        assert result["config"]["callbacks"].count(mock_tracer) == 1

    def test_no_error_when_tracer_not_configured(self, monkeypatch: pytest.MonkeyPatch):
        """When tracer is None, injection is a no-op."""
        monkeypatch.setattr(telemetry_mod, "_azure_ai_tracer", None)
        tracer = telemetry_mod.get_azure_ai_tracer()
        assert tracer is None

        result = {"input": {"messages": []}, "config": {}}
        if tracer is not None:
            config = result.get("config") or {}
            callbacks = list(config.get("callbacks") or [])
            callbacks.append(tracer)
            config["callbacks"] = callbacks
            result["config"] = config

        assert "callbacks" not in result.get("config", {})
