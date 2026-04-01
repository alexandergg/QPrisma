"""
QPrisma State Converter for Azure AI Foundry Hosted Agent
=========================================================

Custom ``LanggraphStateConverter`` that bridges the Foundry Responses API
and QPrisma's LangGraph agent state.

The default ``LanggraphMessageStateConverter`` only maps input messages into
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

Usage::

    from agent.hosted.state_converter import QPrismaStateConverter
    app = from_langgraph(graph, QPrismaStateConverter())
"""

import json
import logging
import re
from typing import Any

from azure.ai.agentserver.core.server.common.agent_run_context import AgentRunContext
from azure.ai.agentserver.langgraph.models import LanggraphMessageStateConverter
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


class QPrismaStateConverter(LanggraphMessageStateConverter):
    """Converter that injects QPrisma video context into the LangGraph state.

    Extends the default message-based converter with extraction of the
    ``[QPRISMA_CONTEXT:...]`` envelope that carries ``media_id`` and
    related metadata through the Foundry Responses API.
    """

    def request_to_state(self, context: AgentRunContext) -> dict[str, Any]:
        """Convert incoming request to LangGraph state with QPrisma context."""
        state = super().request_to_state(context)

        messages = state.get("messages", [])
        if not messages:
            return state

        # Find the last HumanMessage (the current user turn)
        last_human_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx is None:
            return state

        human_msg = messages[last_human_idx]
        content = human_msg.content if isinstance(human_msg.content, str) else ""
        if not content:
            return state

        metadata, cleaned_content = _extract_qprisma_context(content)
        if not metadata:
            logger.debug("No QPRISMA_CONTEXT prefix in user message")
            return state

        # Replace the HumanMessage with the cleaned version
        messages[last_human_idx] = HumanMessage(content=cleaned_content)
        state["messages"] = messages

        # Inject QPrisma fields into the initial graph state
        media_id = metadata.get("media_id")
        media_ids = metadata.get("media_ids")
        user_id = metadata.get("user_id")
        session_id = metadata.get("session_id")

        if media_id:
            state["media_id"] = media_id
        if media_ids:
            state["media_ids"] = media_ids
        if user_id:
            state["user_id"] = user_id
        if session_id:
            state["session_id"] = session_id

        logger.info(
            "QPrismaStateConverter: injected context — " "media_id=%s, media_ids=%s, user_id=%s",
            media_id,
            [mid[:8] + "…" for mid in media_ids] if media_ids else None,
            user_id[:8] + "…" if user_id else None,
        )

        return state
