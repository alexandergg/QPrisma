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

_CONTEXT_PREFIX = "[QPRISMA_CONTEXT:"  # Literal prefix that wraps the JSON context envelope

_json_decoder = json.JSONDecoder()


def _extract_qprisma_context(text: str) -> tuple[dict[str, Any], str]:
    """Parse ``[QPRISMA_CONTEXT:{...}]`` from the beginning of *text*.

    Uses :meth:`json.JSONDecoder.raw_decode` instead of a regex so that
    nested JSON structures (e.g. ``media_ids: [...]``) are handled
    correctly regardless of inner brackets.

    Returns:
        A tuple of (parsed metadata dict, cleaned message text).
        If no prefix is found, returns ({}, original text).
    """
    if not text.startswith(_CONTEXT_PREFIX):
        return {}, text

    json_start = len(_CONTEXT_PREFIX)
    try:
        metadata, json_end = _json_decoder.raw_decode(text, json_start)
    except (json.JSONDecodeError, ValueError):
        logger.warning("QPRISMA_CONTEXT prefix found but JSON is malformed")
        return {}, text

    if not isinstance(metadata, dict):
        logger.warning(
            "QPRISMA_CONTEXT payload is not a JSON object (got %s)", type(metadata).__name__
        )
        return {}, text

    # Expect a closing ']' immediately after the JSON object
    if json_end >= len(text) or text[json_end] != "]":
        logger.warning("QPRISMA_CONTEXT: missing closing ']' after JSON payload")
        return {}, text

    rest_start = json_end + 1  # skip ']'
    if rest_start < len(text) and text[rest_start] == "\n":
        rest_start += 1  # skip optional newline

    return metadata, text[rest_start:]


# ---------------------------------------------------------------------------
# Custom non-stream response converter
# ---------------------------------------------------------------------------


_NODES_TO_SKIP = frozenset({"restore_media_context"})
"""Nodes whose ``messages`` output contains *input-side* state (e.g. full
conversation history for context injection) rather than new agent output.
Emitting these would replay the entire history as new response items."""

_MAX_TOOL_OUTPUT_CHARS = 50_000
"""Maximum character length for tool output strings.  Video tools
(``get_transcript``, ``describe_scene``, ``get_entity_graph``) can produce
very large JSON payloads.  Outputs exceeding this limit are truncated to
prevent oversized responses that the Foundry API may reject."""

# Control characters to strip from tool output (keep \t, \n, \r which are valid in JSON)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_tool_output(content: str) -> str:
    """Remove null bytes and control characters that could break JSON serialization."""
    return _CONTROL_CHAR_RE.sub("", content)


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
        self._attempted_tool_conversions = False

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

        # Compute orphans_dropped before fallback (which may replace `result`)
        orphans_dropped = len(items) - len(result)

        # Fallback: if custom conversion produced nothing from non-empty input
        # AND conversion errors occurred, delegate to the default base-class
        # converter — but ONLY when no tool-call or tool-output items were
        # attempted.  If the converter dropped all items due to malformed
        # tool calls, falling back to super().convert() would recreate the
        # same invalid serialized items and re-trigger Foundry 400 errors.
        if (
            not result
            and output
            and self._conversion_errors > 0
            and not self._attempted_tool_conversions
        ):
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
        elif not result and output and self._conversion_errors > 0:
            logger.warning(
                "Custom converter produced 0 items from %d steps with %d "
                "conversion errors (tool conversions attempted — skipping "
                "fallback to avoid re-triggering invalid format errors)",
                len(output),
                self._conversion_errors,
            )

        tool_call_count = sum(
            1 for i in result if isinstance(i, project_models.FunctionToolCallItemResource)
        )
        tool_output_count = sum(
            1 for i in result if isinstance(i, project_models.FunctionToolCallOutputItemResource)
        )
        message_count = sum(
            1 for i in result if isinstance(i, project_models.ResponsesAssistantMessageItemResource)
        )

        # Elevated to INFO when tool calls are present (the failure-prone path)
        log_fn = logger.info if tool_call_count > 0 else logger.debug
        log_fn(
            "QPrismaNonStreamResponseConverter: produced %d items "
            "(tool_calls=%d, tool_outputs=%d, messages=%d, "
            "conversion_errors=%d, orphans_dropped=%d)",
            len(result),
            tool_call_count,
            tool_output_count,
            message_count,
            self._conversion_errors,
            orphans_dropped,
        )

        # Log item sequence at DEBUG for diagnosing format issues
        if logger.isEnabledFor(logging.DEBUG):
            type_seq = [type(i).__name__ for i in result]
            logger.debug("Item sequence: %s", type_seq)

        # Warn on mismatched tool call/output counts (orphan indicator)
        if tool_call_count != tool_output_count and tool_call_count > 0:
            logger.warning(
                "Tool call/output count mismatch: %d calls vs %d outputs "
                "— orphaned items may have been dropped",
                tool_call_count,
                tool_output_count,
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
        """Convert one LangChain message to zero or more Responses API items.

        Applies defensive validation:

        * **Tool calls** — ``extract_function_call`` can return ``None`` for
          ``name``, ``call_id``, or ``argument``.  ``FunctionToolCallItemResource``
          silently omits ``None`` fields during serialization, producing items
          that are missing required fields and get rejected by Foundry with
          HTTP 400 "invalid format".  We therefore **drop** tool calls whose
          ``name`` or ``call_id`` is ``None`` (unfixable), while defaulting a
          missing ``arguments`` to ``"{}"`` (empty args is semantically valid).
        * **Tool outputs** — dropped when ``tool_call_id`` is ``None`` (no way
          to match it to a tool call).  Content is coerced to a string and
          truncated to ``_MAX_TOOL_OUTPUT_CHARS`` to guard against oversized
          payloads.
        * **Per-item isolation** — each tool call is converted inside its own
          ``try/except`` so a single malformed call does not discard the rest
          of the message's items.
        """
        # Filter out input-side messages — they shouldn't appear in agent output
        if isinstance(message, lc_messages.HumanMessage | lc_messages.SystemMessage):
            return

        if isinstance(message, lc_messages.AIMessage):
            if message.tool_calls:
                self._attempted_tool_conversions = True
                # Emit ALL tool calls (fixes default which only emits the first)
                for tool_call in message.tool_calls:
                    try:
                        name, call_id, argument = extract_function_call(tool_call)

                        # Validate required fields — drop if unfixable
                        if not call_id:
                            logger.warning(
                                "Dropping tool call with missing call_id " "(name=%r, raw=%s)",
                                name,
                                repr(tool_call)[:200],
                            )
                            self._conversion_errors += 1
                            continue
                        if not name:
                            logger.warning(
                                "Dropping tool call with missing name " "(call_id=%r, raw=%s)",
                                call_id,
                                repr(tool_call)[:200],
                            )
                            self._conversion_errors += 1
                            continue

                        # arguments can safely default to empty JSON object
                        if not argument:
                            argument = "{}"

                        yield project_models.FunctionToolCallItemResource(
                            call_id=call_id,
                            name=name,
                            arguments=argument,
                            id=self.context.agent_run.id_generator.generate_function_call_id(),
                            status="completed",
                        )
                    except Exception:
                        self._conversion_errors += 1
                        logger.exception(
                            "Failed to convert tool call: %s",
                            repr(tool_call)[:300],
                        )
                # NOTE: Do NOT emit an assistant message here even if the
                # AIMessage has text content alongside tool_calls (e.g.
                # "Let me search…").  The Responses API treats tool-call
                # turns and assistant-message turns as mutually exclusive —
                # mixing them causes Foundry to reject the response with
                # HTTP 400 "invalid format".  The SDK base converter
                # follows the same pattern.  The final answer (an AIMessage
                # without tool_calls) is always emitted separately.
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
            self._attempted_tool_conversions = True
            # Validate call_id — drop if missing (can't match to a tool call)
            if not message.tool_call_id:
                logger.warning(
                    "Dropping tool output with missing tool_call_id " "(name=%r, content_len=%d)",
                    getattr(message, "name", None),
                    len(str(message.content)) if message.content else 0,
                )
                self._conversion_errors += 1
                return

            content = message.content
            # Coerce to string
            if content is None:
                content = "{}"
            elif not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False)
                except (TypeError, ValueError):
                    content = str(content)

            # Sanitize control characters that could break Foundry serialization
            content = _sanitize_tool_output(content)

            # Truncate oversized tool outputs (reserve room for suffix)
            if len(content) > _MAX_TOOL_OUTPUT_CHARS:
                original_len = len(content)
                suffix = (
                    f"\n[truncated — original {original_len:,} chars "
                    f"exceeded {_MAX_TOOL_OUTPUT_CHARS:,} char limit]"
                )
                content = content[: _MAX_TOOL_OUTPUT_CHARS - len(suffix)] + suffix
                logger.warning(
                    "Truncated tool output for call_id=%s " "(original=%d chars, limit=%d)",
                    message.tool_call_id,
                    original_len,
                    _MAX_TOOL_OUTPUT_CHARS,
                )

            yield project_models.FunctionToolCallOutputItemResource(
                call_id=message.tool_call_id,
                output=content,
                id=self.context.agent_run.id_generator.generate_function_output_id(),
                status="completed",
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
