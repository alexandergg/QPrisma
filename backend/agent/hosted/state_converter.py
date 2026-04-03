"""
QPrisma State Converter for Azure AI Foundry Hosted Agent
=========================================================

Custom ``ResponseAPIConverter`` that bridges the Foundry Responses API
and QPrisma's LangGraph agent state.

The default ``ResponseAPIDefaultConverter`` only maps input messages into
``{"messages": [...]}`` — it has no awareness of QPrisma-specific fields like
``media_id``, ``media_ids``, or ``user_id``.

When the QPrisma backend calls the hosted agent via the Responses API, it
prepends a ``[QPRISMA_CONTEXT:{...}]`` JSON envelope to the user message
(see ``FoundryAgentClient._prepend_context``).  This converter:

1. Delegates base message conversion to the parent class.
2. Scans the last ``HumanMessage`` for the context prefix.
3. Extracts ``media_id``, ``media_ids``, ``user_id``, ``session_id``.
4. Injects them into the initial graph state so downstream nodes
   (``restore_media_context``, ``call_model``) have immediate access.
5. Strips the prefix so the LLM never sees the internal envelope.
6. Injects the ``AzureAIOpenTelemetryTracer`` callback into the
   graph config so Foundry emits Conversation-level traces.

Usage::

    from agent.hosted.state_converter import QPrismaStateConverter
    converter = QPrismaStateConverter(graph=graph)
    app = from_langgraph(graph, converter=converter)
"""

import json
import logging
import re
from typing import Any

from azure.ai.agentserver.langgraph import LanggraphRunContext
from azure.ai.agentserver.langgraph.models.response_api_converter import GraphInputArguments
from azure.ai.agentserver.langgraph.models.response_api_default_converter import (
    ResponseAPIDefaultConverter,
)
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# Regex that matches the context prefix at the start of a message.
# Group 1 captures the JSON payload.
_CONTEXT_RE = re.compile(r"^\[QPRISMA_CONTEXT:(.*?)\]\n?", re.DOTALL)


def _extract_qprisma_context(text: str) -> tuple[dict[str, Any], str]:
    """Parse ``[QPRISMA_CONTEXT:{...}]`` from the beginning of *text*.

    Returns:
        A tuple of (parsed metadata dict, cleaned message text).
        If no prefix is found, returns ({}, original text).
    """
    match = _CONTEXT_RE.match(text)
    if not match:
        return {}, text

    try:
        metadata = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        logger.warning("QPRISMA_CONTEXT prefix found but JSON is malformed")
        return {}, text

    cleaned = text[match.end() :]
    return metadata, cleaned


class QPrismaStateConverter(ResponseAPIDefaultConverter):
    """Converter that injects QPrisma video context into the LangGraph state.

    Extends the default response-API converter with extraction of the
    ``[QPRISMA_CONTEXT:...]`` envelope that carries ``media_id`` and
    related metadata through the Foundry Responses API.
    """

    async def convert_request(self, context: LanggraphRunContext) -> GraphInputArguments:
        """Convert incoming request to LangGraph input with QPrisma context."""
        result = await super().convert_request(context)
        input_data = result["input"]

        # --- Inject AzureAIOpenTelemetryTracer callback for Conversation traces ---
        try:
            from agent.hosted.main import get_azure_ai_tracer

            tracer = get_azure_ai_tracer()
            if tracer is not None:
                config = result.get("config") or {}
                callbacks = list(config.get("callbacks") or [])
                if tracer not in callbacks:
                    callbacks.append(tracer)
                config["callbacks"] = callbacks
                result["config"] = config
                logger.debug("QPrismaStateConverter: injected AzureAIOpenTelemetryTracer callback")
        except Exception as e:
            logger.debug("QPrismaStateConverter: tracer injection skipped (%s)", e)

        if not isinstance(input_data, dict):
            return result

        messages = input_data.get("messages", [])
        if not messages:
            return result

        # Find the last HumanMessage (the current user turn)
        last_human_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx is None:
            return result

        human_msg = messages[last_human_idx]
        content = human_msg.content if isinstance(human_msg.content, str) else ""
        if not content:
            return result

        metadata, cleaned_content = _extract_qprisma_context(content)
        if not metadata:
            logger.debug("No QPRISMA_CONTEXT prefix in user message")
            return result

        # Replace the HumanMessage with the cleaned version
        messages[last_human_idx] = HumanMessage(content=cleaned_content)
        input_data["messages"] = messages

        # Inject QPrisma fields into the initial graph state.
        # Always set InjectedState targets (even as None / []) so that
        # LangGraph's ToolNode._inject_tool_args doesn't KeyError.
        media_id = metadata.get("media_id")
        media_ids = metadata.get("media_ids")
        user_id = metadata.get("user_id")
        session_id = metadata.get("session_id")

        input_data["media_id"] = media_id
        input_data["media_ids"] = media_ids or []
        input_data["user_id"] = user_id
        input_data["session_id"] = session_id

        logger.info(
            "QPrismaStateConverter: injected context — media_id=%s, media_ids=%s, user_id=%s",
            media_id,
            [mid[:8] + "…" for mid in media_ids] if media_ids else None,
            user_id[:8] + "…" if user_id else None,
        )

        return result
