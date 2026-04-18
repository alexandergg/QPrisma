"""
Hosted Agent Telemetry Singleton
================================

Holds the ``AzureAIOpenTelemetryTracer`` singleton so that both
``main.py`` (which creates it) and ``state_converter.py`` (which
injects it as a callback) can access it without a circular import.

Also exposes :class:`SafeAzureAIOpenTelemetryTracer`, a thin adapter
that swallows callback exceptions and normalizes LangGraph's list-shaped
chain inputs into the dict shape expected by ``langchain-azure-ai==1.1.0b1``'s
``AzureAIOpenTelemetryTracer.on_chain_start`` (which calls ``.get(...)`` on
``inputs`` and raises ``AttributeError("'list' object has no attribute 'get'")``
on every node start otherwise).
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


def patch_agentserver_history_fetch() -> bool:
    """Monkeypatch ``azure.ai.agentserver``'s ``_fetch_historical_items``.

    ``azure-ai-agentserver-langgraph==1.0.0b17`` does ``async for item in
    openai_client.conversations.items.list(conversation_id):`` but in
    ``openai>=2.x`` ``AsyncItems.list`` is a coroutine that resolves to an
    async paginator, so the unawaited iteration raises immediately and
    silently drops all conversation history between turns.

    Returns ``True`` if the patch was applied, ``False`` otherwise (already
    patched, library missing, or upstream signature has changed).
    """
    try:
        from azure.ai.agentserver.langgraph.models import (  # type: ignore[import-not-found]
            response_api_default_converter as _converter,
        )
    except Exception as exc:  # pragma: no cover - depends on installed lib
        logger.debug("agentserver patch: module not importable (%s)", exc)
        return False

    if getattr(_converter, "_qprisma_history_patched", False):
        return False

    _original = getattr(_converter, "_fetch_historical_items", None)
    if _original is None:
        logger.debug("agentserver patch: _fetch_historical_items not found")
        return False

    async def _patched_fetch_historical_items(openai_client, conversation_id):  # type: ignore[no-untyped-def]
        items: list[Any] = []
        try:
            paginator = openai_client.conversations.items.list(conversation_id)
            # Some openai SDK versions return a coroutine that resolves to the
            # async paginator; others return the paginator directly. Handle both.
            if hasattr(paginator, "__await__"):
                paginator = await paginator  # type: ignore[assignment]
            async for item in paginator:
                items.append(item)
        except Exception as exc:
            logger.warning(
                "agentserver patched _fetch_historical_items failed for %s: %s",
                conversation_id,
                exc,
            )
            return []
        return items

    _converter._fetch_historical_items = _patched_fetch_historical_items
    _converter._qprisma_history_patched = True
    logger.info(
        "agentserver patch: replaced _fetch_historical_items "
        "(awaits AsyncItems.list before iterating)"
    )
    return True
