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

import contextvars
import json
import logging
import os
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

from agent.context_envelopes import (
    QPRISMA_BENCH_PREFIX,
    QPRISMA_CONTEXT_PREFIX,
    extract_qprisma_envelopes,
    normalize_media_selection,
)

logger = logging.getLogger(__name__)

# Async-safe per-request response mode.  Set during convert_request() and
# read by _create_qprisma_converter() so overlapping async requests never
# leak modes across each other.
_request_response_mode: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_request_response_mode", default="full"
)


def _extract_qprisma_envelopes(text: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Parse QPrisma context/benchmark envelopes from the beginning of *text*."""
    context, benchmark, cleaned = extract_qprisma_envelopes(text)
    if cleaned == text and text.startswith(QPRISMA_CONTEXT_PREFIX):
        logger.warning("QPRISMA_CONTEXT prefix found but payload is malformed")
    if cleaned == text and text.startswith(QPRISMA_BENCH_PREFIX):
        logger.warning("QPRISMA_BENCH prefix found but payload is malformed")
    return context, benchmark, cleaned


def _extract_qprisma_context(text: str) -> tuple[dict[str, Any], str]:
    """Parse ``[QPRISMA_CONTEXT:{...}]`` and adjacent eval envelopes from *text*.

    Uses :meth:`json.JSONDecoder.raw_decode` instead of a regex so that
    nested JSON structures (e.g. ``media_ids: [...]``) are handled
    correctly regardless of inner brackets.

    Returns:
        A tuple of (parsed metadata dict, cleaned message text).
        If no prefix is found, returns ({}, original text).
    """
    metadata, _, cleaned = _extract_qprisma_envelopes(text)
    return metadata, cleaned


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

# Valid response_mode values: "full" (default) or "final_answer" (eval-friendly)
VALID_RESPONSE_MODES = frozenset({"full", "final_answer"})


def _sanitize_tool_output(content: str) -> str:
    """Remove null bytes and control characters that could break JSON serialization."""
    return _CONTROL_CHAR_RE.sub("", content)


# Last-resort placeholder used when `response_mode="final_answer"` strips all
# tool items and no AIMessage text survived.  Foundry's Responses API rejects
# empty response batches with HTTP 400 "Response could not be saved due to
# invalid format", so we always emit at least one assistant message.
_FINAL_ANSWER_EMPTY_PLACEHOLDER = (
    "I couldn't produce a final answer for this request. "
    "Please try again or rephrase your question."
)


def _extract_ai_text(message: Any) -> str:
    """Return the plain-text content of an AIMessage, or ``""`` if none.

    LangChain ``AIMessage.content`` may be a string *or* a list of content
    blocks (Anthropic style).  This helper flattens list content by joining
    the ``text`` of every ``type="text"`` block so we can use AIMessage
    content that accompanies tool_calls as a fallback final answer.
    """
    content = getattr(message, "content", None)
    if not content:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def _content_shape_summary(content: Any) -> str:
    """Return a short human-readable summary of an assistant item's ``content``.

    Used by the post-conversion invariant log to confirm that every
    ``ResponsesAssistantMessageItemResource`` emitted by the converter carries
    a list of typed SDK content parts (``ItemContent`` / similar) rather than
    a raw string or JSON-stringified array — a symptom previously observed in
    Foundry evaluation runs where ``sample.output[*].content`` was stored as
    ``"[{\\"type\\":\\"output_text\\",...}]"`` instead of a proper typed list,
    which caused evaluators to fail with ``Response is a required input and
    cannot be None``.
    """
    if content is None:
        return "None"
    if isinstance(content, str):
        return f"str(len={len(content)})"
    if isinstance(content, list):
        if not content:
            return "list(empty)"
        element_types = {type(el).__name__ for el in content}
        return f"list(len={len(content)}, element_types={sorted(element_types)})"
    return type(content).__name__


def _assistant_item_is_empty(item: Any) -> bool:
    """Return True when a ``ResponsesAssistantMessageItemResource`` carries
    no non-whitespace text.

    ``_convert_single_message`` emits an assistant item unconditionally for
    every tool-free ``AIMessage`` — including ones whose ``content`` is an
    empty string.  Those pass-through empty items would slip past the
    ``not assistant_items`` guard in ``final_answer`` mode and still cause
    Foundry to reject the response.  This helper mirrors ``_extract_ai_text``
    so the guard can detect them regardless of whether the SDK stores
    ``item.content`` as a plain string or as a list of content-part objects
    (dicts with a ``"text"`` key or objects exposing a ``.text`` attribute).
    """
    content = getattr(item, "content", None)
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                if block.strip():
                    return False
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return False
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    return False
        return True
    return not str(content).strip()


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

    When ``response_mode="final_answer"``, the converter performs the full
    internal conversion but strips all tool-call and tool-output items from the
    final output, keeping only ``ResponsesAssistantMessageItemResource`` items.
    This allows Foundry's evaluation pipeline to save the response without
    encountering "invalid format" errors from tool-related items.
    """

    def __init__(self, context, hitl_helper, *, response_mode: str = "full"):
        super().__init__(context, hitl_helper)
        if response_mode not in VALID_RESPONSE_MODES:
            logger.warning("Unknown response_mode %r — falling back to 'full'", response_mode)
            response_mode = "full"
        self._response_mode = response_mode

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

        # Track the last AIMessage text content seen in the stream so we can
        # use it as a fallback final answer in `final_answer` mode when the
        # post-stripping result would otherwise be empty.  Preambles on
        # tool-calling AIMessages are normally discarded by
        # ``_convert_single_message`` (mutually-exclusive turn rule), but in
        # ``final_answer`` mode tool items are stripped anyway — so the
        # preamble is safe (and valuable) to surface.
        last_ai_text: str = ""

        for step in output:
            if not isinstance(step, dict):
                logger.warning("Skipping non-dict step of type %s", type(step).__name__)
                continue
            for node_name, node_output in step.items():
                if node_name not in _NODES_TO_SKIP and isinstance(node_output, dict):
                    msgs = node_output.get("messages")
                    if isinstance(msgs, Collection):
                        for msg in msgs:
                            if isinstance(msg, lc_messages.AIMessage):
                                text = _extract_ai_text(msg)
                                if text:
                                    last_ai_text = text
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

        # --- final_answer mode: strip tool items for eval-friendly output ---
        if self._response_mode == "final_answer":
            full_count = len(result)
            assistant_items = [
                item
                for item in result
                if isinstance(item, project_models.ResponsesAssistantMessageItemResource)
            ]
            stripped = full_count - len(assistant_items)

            # Collapse multiple assistant messages to the last non-empty one.
            # The Responses API treats the response as a single assistant
            # turn; emitting multiple ResponsesAssistantMessageItemResource
            # has been observed to trigger Foundry "invalid format" 400s.
            collapsed_from = len(assistant_items)
            if len(assistant_items) > 1:
                assistant_items = [assistant_items[-1]]

            # Guarantee non-empty: Foundry rejects empty responses with
            # HTTP 400 "Response could not be saved due to invalid format".
            # We need a fallback both when no assistant message survived
            # stripping (e.g. the final graph step was a tool call or
            # ``max_iterations`` was hit) AND when the surviving assistant
            # message carries empty/whitespace content — ``_convert_single_message``
            # emits an assistant item for every tool-free AIMessage, even one
            # with ``content=""``, so ``assistant_items`` can be non-empty
            # while still being unusable.  Only synthesize when the graph
            # actually produced output — a truly empty ``output`` list means
            # the graph never ran and Foundry handles that upstream.
            synthesized = False
            surviving_empty = bool(assistant_items) and _assistant_item_is_empty(
                assistant_items[-1]
            )
            if output and (not assistant_items or surviving_empty):
                fallback_text = last_ai_text or _FINAL_ANSWER_EMPTY_PLACEHOLDER
                try:
                    # Replace any empty surviving message rather than append,
                    # preserving the single-assistant-turn contract.
                    assistant_items = [
                        project_models.ResponsesAssistantMessageItemResource(
                            content=self.convert_MessageContent(
                                fallback_text,
                                role=project_models.ResponsesMessageRole.ASSISTANT,
                            ),
                            id=self.context.agent_run.id_generator.generate_message_id(),
                            status="completed",
                        )
                    ]
                    synthesized = True
                    logger.warning(
                        "response_mode=final_answer: %s (stripped=%d, "
                        "last_ai_text_len=%d); synthesized fallback from %s",
                        (
                            "surviving assistant message was empty/whitespace"
                            if surviving_empty
                            else "no assistant message survived stripping"
                        ),
                        stripped,
                        len(last_ai_text),
                        "last AIMessage text" if last_ai_text else "empty-placeholder",
                    )
                except Exception:
                    logger.exception(
                        "response_mode=final_answer: failed to synthesize fallback "
                        "assistant message — Foundry will reject empty response"
                    )

            result = assistant_items
            logger.info(
                "response_mode=final_answer: stripped=%d tool items, "
                "collapsed=%d assistant messages, synthesized_fallback=%s, "
                "final_count=%d",
                stripped,
                max(0, collapsed_from - len(result)) if not synthesized else 0,
                synthesized,
                len(result),
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

        # --- Post-conversion content-shape invariant + defensive repair ---
        #
        # The Foundry Responses API requires ``ResponsesAssistantMessageItemResource.content``
        # to be a list of typed SDK content parts (``ItemContent`` and friends).
        # If ``content`` is ever emitted as a plain string — or as a list
        # containing a plain string / raw dict — downstream evaluation
        # pipelines (e.g. ``microsoft/ai-agent-evals@v3-beta``) can fail to
        # resolve ``sample.output[*].content`` as a valid response and abort
        # every row with ``(UserError) Response is a required input and
        # cannot be None``.  This happened in the v52 hosted-agent deployment
        # despite the converter calling ``convert_MessageContent`` on every
        # code path.
        #
        # The loop below acts as a final safety net: it logs unexpected
        # content shapes at WARNING and otherwise keeps shape diagnostics at
        # DEBUG so production logs are not flooded by healthy assistant items.
        # If a malformed shape is detected, it re-runs
        # ``convert_MessageContent`` on a flattened plain-text representation
        # to guarantee typed output.
        for idx, item in enumerate(result):
            if not isinstance(item, project_models.ResponsesAssistantMessageItemResource):
                continue
            content = getattr(item, "content", None)
            shape = _content_shape_summary(content)
            needs_repair = False
            if isinstance(content, str):
                needs_repair = True
            elif isinstance(content, list):
                for el in content:
                    # Typed SDK parts expose ``.text``/``.type`` attrs; raw
                    # strings or untyped dicts slipping through indicate the
                    # content was not routed through ``convert_MessageContent``
                    # and must be repaired to avoid stringified storage.
                    if isinstance(el, str | dict):
                        needs_repair = True
                        break
            elif content is None:
                needs_repair = True

            if needs_repair:
                logger.warning(
                    "Assistant item %d has malformed content shape %s — "
                    "re-wrapping via convert_MessageContent (defensive repair)",
                    idx,
                    shape,
                )
                try:
                    fallback_text = _extract_ai_text(item) or _FINAL_ANSWER_EMPTY_PLACEHOLDER
                    item.content = self.convert_MessageContent(
                        fallback_text,
                        role=project_models.ResponsesMessageRole.ASSISTANT,
                    )
                except Exception:
                    logger.exception("Defensive content repair failed for assistant item %d", idx)
            else:
                logger.debug("Assistant item %d content shape OK: %s", idx, shape)

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
    - **response_mode**: per-query or env-var control over response item filtering
      (``"full"`` = all items, ``"final_answer"`` = assistant messages only)
    """

    def __init__(self, graph):
        super().__init__(
            graph=graph,
            create_non_stream_response_converter=self._create_qprisma_converter,
        )
        self._default_response_mode = os.environ.get("QPRISMA_RESPONSE_MODE", "full")
        if self._default_response_mode not in VALID_RESPONSE_MODES:
            logger.warning(
                "QPRISMA_RESPONSE_MODE=%r is invalid — falling back to 'full'",
                self._default_response_mode,
            )
            self._default_response_mode = "full"

    def _create_qprisma_converter(
        self, context: LanggraphRunContext
    ) -> QPrismaNonStreamResponseConverter:
        """Factory for the custom non-stream response converter.

        Reads the response mode from the async-safe ``_request_response_mode``
        ContextVar (set during ``convert_request``) so that overlapping
        async requests never leak modes across each other.
        """
        hitl_helper = self._create_human_in_the_loop_helper(context)
        mode = _request_response_mode.get(self._default_response_mode)
        return QPrismaNonStreamResponseConverter(context, hitl_helper, response_mode=mode)

    async def convert_request(self, context: LanggraphRunContext) -> GraphInputArguments:
        """Convert incoming request to LangGraph input with QPrisma context."""
        # Reset response mode to default at the start of every request so that
        # early-return paths never inherit a stale override from a previous call.
        _request_response_mode.set(self._default_response_mode)

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

        metadata, benchmark_context, cleaned_content = _extract_qprisma_envelopes(content)
        if not metadata and not benchmark_context:
            logger.debug("No QPRISMA_CONTEXT/QPRISMA_BENCH prefix in user message")
            return result

        # Extract response_mode override before stripping metadata from the message
        query_response_mode = metadata.pop("response_mode", None)
        if query_response_mode and query_response_mode in VALID_RESPONSE_MODES:
            _request_response_mode.set(query_response_mode)
            logger.info("QPrismaStateConverter: response_mode=%s (per-query)", query_response_mode)

        # Replace the HumanMessage with the cleaned version
        messages[last_human_idx] = HumanMessage(content=cleaned_content)
        input_data["messages"] = messages

        # Inject QPrisma fields into the initial graph state.
        # Always set InjectedState targets (even as None / []) so that
        # LangGraph's ToolNode._inject_tool_args doesn't KeyError.
        media_id, media_ids = normalize_media_selection(
            metadata.get("media_id"),
            metadata.get("media_ids"),
        )
        user_id = metadata.get("user_id")
        session_id = metadata.get("session_id")

        input_data["media_id"] = media_id
        input_data["media_ids"] = media_ids
        input_data["user_id"] = user_id
        input_data["session_id"] = session_id
        if benchmark_context:
            input_data["benchmark_context"] = benchmark_context

        logger.info(
            "QPrismaStateConverter: injected context — media_id=%s, media_ids=%s, "
            "user_id=%s, benchmark=%s",
            media_id,
            [mid[:8] + "…" for mid in media_ids] if media_ids else None,
            user_id[:8] + "…" if user_id else None,
            bool(benchmark_context),
        )

        return result
