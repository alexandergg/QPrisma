"""
QPrisma State Converter for Azure AI Foundry Hosted Agent
=========================================================

Custom ``ResponseAPIConverter`` that bridges the Foundry Responses API
and QPrisma's LangGraph agent state.

**Request conversion** (``convert_request``):
    The default converter only maps input messages into ``{"messages": [...]}``.
    QPrisma extends this to extract ``[QPRISMA_CONTEXT:{...}]`` envelopes that
    carry ``media_id``, ``user_id``, etc. through the Responses API.

**Response conversion** (``QPrismaNonStreamResponseConverter``):
    The default ``ResponseAPIMessagesNonStreamResponseConverter`` has a known
    limitation: it only emits the **first** ``tool_call`` per ``AIMessage``,
    silently dropping the rest.  QPrisma's agent routinely makes 2-3 parallel
    tool calls per turn, which creates orphaned ``ToolMessage`` outputs whose
    ``call_id`` references a tool call that was never emitted.  The Foundry
    Responses API rejects such responses as *"invalid format"*.

    The custom converter fixes this by:
    - Emitting **all** ``FunctionToolCallItemResource`` objects per ``AIMessage``
    - Tracking emitted ``call_id`` values and dropping orphaned tool outputs
    - Filtering ``HumanMessage`` / ``SystemMessage`` from output (input, not output)

Usage::

    from agent.hosted.state_converter import QPrismaStateConverter
    converter = QPrismaStateConverter(graph=graph)
    app = from_langgraph(graph, converter=converter)
"""

import json
import logging
import re
from collections.abc import Collection, Iterable
from typing import Any

from azure.ai.agentserver.core.models import projects as project_models
from azure.ai.agentserver.langgraph import LanggraphRunContext
from azure.ai.agentserver.langgraph.models.response_api_converter import GraphInputArguments
from azure.ai.agentserver.langgraph.models.response_api_default_converter import (
    ResponseAPIDefaultConverter,
)
from azure.ai.agentserver.langgraph.models.response_api_non_stream_response_converter import (
    INTERRUPT_NODE_NAME,
    ResponseAPIMessagesNonStreamResponseConverter,
)
from azure.ai.agentserver.langgraph.models.utils import extract_function_call
from langchain_core import messages as lc_messages
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


# ---------------------------------------------------------------------------
# Custom non-stream response converter
# ---------------------------------------------------------------------------


_NODES_TO_SKIP = frozenset({"restore_media_context"})
"""Nodes whose ``messages`` output contains *input-side* state (e.g. full
conversation history for context injection) rather than new agent output.
Emitting these would replay the entire history as new response items."""


class QPrismaNonStreamResponseConverter(ResponseAPIMessagesNonStreamResponseConverter):
    """Convert LangGraph ``stream_mode="updates"`` output to Responses API items.

    Fixes three issues in the default converter:

    1. **Multi-tool-call support** — emits a ``FunctionToolCallItemResource`` for
       *every* ``tool_call`` in an ``AIMessage``, not just the first.
    2. **Orphan-output guard** — tracks emitted ``call_id`` values and silently
       drops any ``FunctionToolCallOutputItemResource`` whose ``call_id`` was
       never emitted, preventing Foundry "invalid format" rejections.
    3. **Node-level filtering** — ``restore_media_context`` is skipped entirely
       because it returns cleaned conversation history (input), not new output.
       As defense-in-depth, ``HumanMessage`` / ``SystemMessage`` from any node
       are also filtered since they represent input context, not agent output.
    """

    def convert(self, output: list[dict[str, Any]]) -> list[project_models.ItemResource]:
        """Two-pass conversion: emit items, then drop orphaned tool outputs.

        Falls back to the default base-class converter if the custom logic
        produces zero items from a non-empty output (defensive safety net).
        """
        if not isinstance(output, list):
            logger.error("Expected output to be a list, got %s", type(output))
            raise ValueError(f"Invalid output format. Expected a list, got {type(output)}.")

        logger.debug(
            "QPrismaNonStreamResponseConverter: output has %d steps, types=%s",
            len(output),
            [type(s).__name__ for s in output[:5]],
        )

        # Pass 1 — convert all steps into candidate items
        items: list[project_models.ItemResource] = []
        emitted_call_ids: set[str] = set()
        self._conversion_errors = 0

        for step in output:
            if not isinstance(step, dict):
                logger.warning("Skipping non-dict step of type %s", type(step).__name__)
                continue
            for node_name, node_output in step.items():
                for item in self._convert_node_output_multi(node_name, node_output):
                    items.append(item)
                    if isinstance(item, project_models.FunctionToolCallItemResource):
                        emitted_call_ids.add(item.call_id)

        # Pass 2 — drop orphaned tool outputs
        result: list[project_models.ItemResource] = []
        for item in items:
            if (
                isinstance(item, project_models.FunctionToolCallOutputItemResource)
                and item.call_id not in emitted_call_ids
            ):
                logger.warning(
                    "Dropping orphaned tool output (call_id=%s) — "
                    "no matching FunctionToolCallItemResource emitted",
                    item.call_id,
                )
                continue
            result.append(item)

        # Fallback: if custom conversion produced nothing from non-empty input
        # AND conversion errors occurred, delegate to the default base-class
        # converter for v38-like behavior.  We only fall back when errors were
        # observed — intentional filtering (orphan drops, node skips) should
        # NOT trigger the fallback.
        if not result and output and self._conversion_errors > 0:
            logger.warning(
                "Custom converter produced 0 items from %d steps with %d "
                "conversion errors — falling back to default base-class converter",
                len(output),
                self._conversion_errors,
            )
            try:
                result = super().convert(output)
                logger.info("Base-class fallback produced %d items", len(result))
            except Exception:
                logger.exception("Base-class fallback also failed")
                raise

        logger.debug(
            "QPrismaNonStreamResponseConverter: produced %d items "
            "(tool_calls=%d, tool_outputs=%d, messages=%d)",
            len(result),
            sum(1 for i in result if isinstance(i, project_models.FunctionToolCallItemResource)),
            sum(
                1
                for i in result
                if isinstance(i, project_models.FunctionToolCallOutputItemResource)
            ),
            sum(
                1
                for i in result
                if isinstance(i, project_models.ResponsesAssistantMessageItemResource)
            ),
        )

        return result

    def _convert_node_output_multi(
        self, node_name: str, node_output: Any
    ) -> Iterable[project_models.ItemResource]:
        """Yield Responses API items for a single graph node update."""
        if node_name == INTERRUPT_NODE_NAME:
            yield from self.hitl_helper.convert_interrupts(node_output)
            return

        if node_name in _NODES_TO_SKIP:
            return

        message_arr = node_output.get("messages") if isinstance(node_output, dict) else None
        if not message_arr or not isinstance(message_arr, Collection):
            logger.debug(
                "Node '%s': no messages key or not a collection (output type=%s, keys=%s)",
                node_name,
                type(node_output).__name__,
                list(node_output.keys()) if isinstance(node_output, dict) else "N/A",
            )
            return

        for message in message_arr:
            try:
                items = list(self._convert_single_message(message))
                if isinstance(message, lc_messages.AIMessage) and not items:
                    logger.warning(
                        "AIMessage from node '%s' yielded 0 items " "(content=%s, tool_calls=%d)",
                        node_name,
                        repr(str(message.content)[:100]) if message.content else "empty",
                        len(message.tool_calls) if message.tool_calls else 0,
                    )
                yield from items
            except Exception:
                self._conversion_errors += 1
                logger.exception(
                    "Error converting %s from node '%s'",
                    type(message).__name__,
                    node_name,
                )

    def _convert_single_message(self, message: Any) -> Iterable[project_models.ItemResource]:
        """Convert one LangChain message to zero or more Responses API items."""
        # Filter out input-side messages — they shouldn't appear in agent output
        if isinstance(message, lc_messages.HumanMessage | lc_messages.SystemMessage):
            return

        if isinstance(message, lc_messages.AIMessage):
            if message.tool_calls:
                # Emit ALL tool calls (fixes default which only emits the first)
                for tool_call in message.tool_calls:
                    name, call_id, argument = extract_function_call(tool_call)
                    yield project_models.FunctionToolCallItemResource(
                        call_id=call_id,
                        name=name,
                        arguments=argument,
                        id=self.context.agent_run.id_generator.generate_function_call_id(),
                        status="completed",
                    )
                # If the AIMessage also has text content alongside tool calls, emit it
                if message.content and str(message.content).strip():
                    yield project_models.ResponsesAssistantMessageItemResource(
                        content=self.convert_MessageContent(
                            message.content,
                            role=project_models.ResponsesMessageRole.ASSISTANT,
                        ),
                        id=self.context.agent_run.id_generator.generate_message_id(),
                        status="completed",
                    )
            else:
                yield project_models.ResponsesAssistantMessageItemResource(
                    content=self.convert_MessageContent(
                        message.content,
                        role=project_models.ResponsesMessageRole.ASSISTANT,
                    ),
                    id=self.context.agent_run.id_generator.generate_message_id(),
                    status="completed",
                )
            return

        if isinstance(message, lc_messages.ToolMessage):
            content = message.content
            if not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False)
                except (TypeError, ValueError):
                    content = str(content)
            yield project_models.FunctionToolCallOutputItemResource(
                call_id=message.tool_call_id,
                output=content,
                id=self.context.agent_run.id_generator.generate_function_output_id(),
            )
            return

        logger.warning("Unsupported message type: %s", type(message).__name__)


# ---------------------------------------------------------------------------
# Main state converter
# ---------------------------------------------------------------------------


class QPrismaStateConverter(ResponseAPIDefaultConverter):
    """Converter that injects QPrisma video context into the LangGraph state.

    Extends the default response-API converter with:
    - **Request**: extraction of the ``[QPRISMA_CONTEXT:...]`` envelope
    - **Response**: multi-tool-call support via ``QPrismaNonStreamResponseConverter``
    """

    def __init__(self, graph):
        super().__init__(
            graph=graph,
            create_non_stream_response_converter=self._create_qprisma_converter,
        )

    def _create_qprisma_converter(
        self, context: LanggraphRunContext
    ) -> QPrismaNonStreamResponseConverter:
        """Factory for the custom non-stream response converter."""
        hitl_helper = self._create_human_in_the_loop_helper(context)
        return QPrismaNonStreamResponseConverter(context, hitl_helper)

    async def convert_request(self, context: LanggraphRunContext) -> GraphInputArguments:
        """Convert incoming request to LangGraph input with QPrisma context."""
        result = await super().convert_request(context)
        input_data = result["input"]

        # --- Inject AzureAIOpenTelemetryTracer callback for Conversation traces ---
        try:
            from agent.hosted.telemetry import get_azure_ai_tracer

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
