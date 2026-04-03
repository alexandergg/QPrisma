"""
Hosted Agent Telemetry Singleton
================================

Holds the ``AzureAIOpenTelemetryTracer`` singleton so that both
``main.py`` (which creates it) and ``state_converter.py`` (which
injects it as a callback) can access it without a circular import.
"""

from typing import Any

# Module-level singleton for the Azure AI tracer (set by main._setup_telemetry)
_azure_ai_tracer: Any | None = None


def get_azure_ai_tracer() -> Any | None:
    """Return the module-level AzureAIOpenTelemetryTracer, if configured."""
    return _azure_ai_tracer


def set_azure_ai_tracer(tracer: Any | None) -> None:
    """Store the AzureAIOpenTelemetryTracer singleton (called once at startup)."""
    global _azure_ai_tracer
    _azure_ai_tracer = tracer
