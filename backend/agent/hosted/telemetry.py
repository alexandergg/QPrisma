"""
Hosted Agent Telemetry Helpers
==============================

Holds the ``AzureAIOpenTelemetryTracer`` singleton so that the hosted
runtime (``main.py``) and any node code that wants to attach extra
callbacks can share the same instance without a circular import.

Also exposes :class:`SafeAzureAIOpenTelemetryTracer`, a thin adapter
that swallows callback exceptions and normalizes LangGraph's list-shaped
chain inputs into the dict shape expected by ``langchain-azure-ai==1.1.0b1``'s
``AzureAIOpenTelemetryTracer.on_chain_start`` (which calls ``.get(...)`` on
``inputs`` and raises ``AttributeError("'list' object has no attribute 'get'")``
on every node start otherwise). Once the upstream bug is fixed this wrapper
can be deleted.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

# Module-level singleton for the Azure AI tracer (set by main._setup_telemetry)
_azure_ai_tracer: Any | None = None


def get_azure_ai_tracer() -> Any | None:
    """Return the module-level AzureAIOpenTelemetryTracer, if configured."""
    return _azure_ai_tracer


def set_azure_ai_tracer(tracer: Any | None) -> None:
    """Store the AzureAIOpenTelemetryTracer singleton (called once at startup)."""
    global _azure_ai_tracer
    _azure_ai_tracer = tracer


class SafeAzureAIOpenTelemetryTracer(BaseCallbackHandler):
    """Adapter that protects ``AzureAIOpenTelemetryTracer`` from LangGraph quirks.

    - Wraps every ``on_*`` callback in ``try/except`` so an upstream tracer
      bug never crashes (or is even noisily logged by) the LangGraph runtime.
    - Normalizes ``inputs`` for ``on_chain_start``/``on_chain_end`` from a
      ``list`` (LangGraph's shape when chain inputs are message arrays) to
      ``{"messages": [...]}`` so the underlying tracer's ``.get(...)`` call
      succeeds.
    - Suppresses repeated identical errors (``(callback, error_type)`` key)
      so the logs surface novel failures instead of a flood of duplicates.
    """

    def __init__(self, inner: Any) -> None:
        super().__init__()
        self._inner = inner
        self._seen_errors: set[tuple[str, str]] = set()

    @staticmethod
    def _normalize_inputs(value: Any) -> Any:
        """Coerce list-shaped chain inputs to a dict the inner tracer expects."""
        if isinstance(value, list):
            return {"messages": value}
        return value

    def _delegate(self, name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self._inner, name, None)
        if method is None:
            return None
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            key = (name, type(exc).__name__)
            if key not in self._seen_errors:
                self._seen_errors.add(key)
                logger.debug(
                    "SafeAzureAIOpenTelemetryTracer: suppressed %s in %s (%s)",
                    type(exc).__name__,
                    name,
                    exc,
                )
            return None

    # --- Forwarded callbacks (normalize shape where the inner tracer is buggy) ---

    def on_chain_start(self, serialized, inputs, **kwargs):  # type: ignore[override]
        return self._delegate(
            "on_chain_start", serialized, self._normalize_inputs(inputs), **kwargs
        )

    def on_chain_end(self, outputs, **kwargs):  # type: ignore[override]
        return self._delegate("on_chain_end", self._normalize_inputs(outputs), **kwargs)

    def on_chain_error(self, error, **kwargs):  # type: ignore[override]
        return self._delegate("on_chain_error", error, **kwargs)

    def on_llm_start(self, serialized, prompts, **kwargs):  # type: ignore[override]
        return self._delegate("on_llm_start", serialized, prompts, **kwargs)

    def on_chat_model_start(self, serialized, messages, **kwargs):  # type: ignore[override]
        return self._delegate("on_chat_model_start", serialized, messages, **kwargs)

    def on_llm_new_token(self, token, **kwargs):  # type: ignore[override]
        return self._delegate("on_llm_new_token", token, **kwargs)

    def on_llm_end(self, response, **kwargs):  # type: ignore[override]
        return self._delegate("on_llm_end", response, **kwargs)

    def on_llm_error(self, error, **kwargs):  # type: ignore[override]
        return self._delegate("on_llm_error", error, **kwargs)

    def on_tool_start(self, serialized, input_str, **kwargs):  # type: ignore[override]
        return self._delegate("on_tool_start", serialized, input_str, **kwargs)

    def on_tool_end(self, output, **kwargs):  # type: ignore[override]
        return self._delegate("on_tool_end", output, **kwargs)

    def on_tool_error(self, error, **kwargs):  # type: ignore[override]
        return self._delegate("on_tool_error", error, **kwargs)

    def on_agent_action(self, action, **kwargs):  # type: ignore[override]
        return self._delegate("on_agent_action", action, **kwargs)

    def on_agent_finish(self, finish, **kwargs):  # type: ignore[override]
        return self._delegate("on_agent_finish", finish, **kwargs)

    def on_text(self, text, **kwargs):  # type: ignore[override]
        return self._delegate("on_text", text, **kwargs)

    def on_retry(self, retry_state, **kwargs):  # type: ignore[override]
        return self._delegate("on_retry", retry_state, **kwargs)
