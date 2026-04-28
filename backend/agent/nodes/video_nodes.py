"""
Video Agent Nodes
=================

Nodes for the LangGraph-based video agent.
Uses shared base implementation with video-specific configuration.
"""

import json
import logging
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.nodes.base import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_WARN_TOOL_ITERATIONS,
    base_call_model,
    base_should_continue,
    select_tools_for_query,
    update_context_node,
)
from agent.prompts import MULTI_VIDEO_SYSTEM_PROMPT, NO_VIDEO_CONTEXT_PROMPT, SYSTEM_PROMPT
from agent.state.agent_state import AgentState, VideoContext
from agent.tools import SEARCH_TOOLS
from agent.utils.media_helpers import is_letter_only_benchmark, normalize_media_selection
from core.config import settings

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = DEFAULT_MAX_TOOL_ITERATIONS
WARN_TOOL_ITERATIONS = DEFAULT_WARN_TOOL_ITERATIONS

# Regex for QPRISMA_CONTEXT/QPRISMA_BENCH envelope prefixes embedded in
# message content by the Video-MME evaluation pipeline.
_CONTEXT_ENV_RE = re.compile(r"\[QPRISMA_CONTEXT:(\{[^{}]*\})\]")
_BENCH_ENV_RE = re.compile(r"\[QPRISMA_BENCH:(\{[^{}]*\})\]")


def _extract_message_envelopes(messages: list, updates: dict) -> None:
    """Parse QPRISMA_CONTEXT/QPRISMA_BENCH envelope prefixes from the first HumanMessage.

    The Video-MME evaluation pipeline embeds context into the message content
    as ``[QPRISMA_CONTEXT:{...}][QPRISMA_BENCH:{...}]\\nActual question``.
    This helper extracts those envelopes, populates *updates* with the resolved
    media/benchmark fields, and rewrites the message with stripped content.
    Only called when config and state both lack a ``media_id``.
    """
    if not messages:
        return

    first_msg = messages[0]
    if not isinstance(first_msg, HumanMessage) or not isinstance(first_msg.content, str):
        return

    content = first_msg.content
    ctx_match = _CONTEXT_ENV_RE.search(content)
    if not ctx_match:
        return

    try:
        ctx = json.loads(ctx_match.group(1))
    except json.JSONDecodeError:
        logger.warning("QPRISMA_CONTEXT prefix found but payload is malformed")
        return

    msg_media_ids = ctx.get("media_ids") or []
    msg_media_id = ctx.get("media_id") or (msg_media_ids[0] if msg_media_ids else None)
    msg_user_id = ctx.get("user_id")

    if msg_media_id:
        updates["media_id"] = msg_media_id
        updates["video_context"] = VideoContext(media_id=msg_media_id)
    if msg_media_ids:
        updates["media_ids"] = msg_media_ids
    if msg_user_id:
        updates["user_id"] = msg_user_id

    # Strip QPRISMA_CONTEXT envelope from content
    content = content[: ctx_match.start()] + content[ctx_match.end() :]

    # Parse and strip QPRISMA_BENCH envelope (whether valid or not)
    bench_match = _BENCH_ENV_RE.search(content)
    if bench_match:
        try:
            updates["benchmark_context"] = json.loads(bench_match.group(1))
        except json.JSONDecodeError:
            logger.warning("QPRISMA_BENCH prefix found but payload is malformed")
        content = content[: bench_match.start()] + content[bench_match.end() :]

    # Strip leading newlines left after removing envelopes
    content = content.lstrip("\n")

    # Rewrite the message with cleaned content (same ID triggers an upsert via add_messages)
    updates["messages"] = [first_msg.model_copy(update={"content": content})] + list(messages[1:])


def _resolve_video_titles(media_ids: list[str]) -> dict[str, str]:
    """
    Look up human-readable titles for a list of media IDs.

    Uses DatabaseService (PostgreSQL) which stores the original filename.
    Falls back gracefully — unknown IDs get "Untitled".
    """
    titles: dict[str, str] = {}
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        for mid in media_ids:
            try:
                media = db.get_media(mid)
                if media:
                    titles[mid] = media.original_filename or media.blob_name or "Untitled"
                else:
                    titles[mid] = "Untitled"
            except Exception:
                titles[mid] = "Untitled"
    except Exception as e:
        logger.warning(f"_resolve_video_titles: failed to resolve titles: {e}")
        for mid in media_ids:
            titles[mid] = "Untitled"
    return titles


def restore_media_context(state: AgentState, config: RunnableConfig) -> dict:
    """
    Resolve media context from request metadata and checkpointed state.

    Priority order for resolving media_id:
    1. ``config.configurable["media_id"]`` — fresh value passed from the
       refreshed-preview hosted runtime (`request.metadata`) or from a
       direct LangGraph caller.
    2. ``state["media_id"]`` — value already preserved on the AgentState
       (e.g. seeded by ``main.py`` or carried over from a previous turn).

    In multi-video mode, also resolves human-readable video titles from the
    database so the system prompt can display them.

    Also stamps OpenTelemetry span attributes (``gen_ai.conversation.id``,
    ``enduser.id``) so Azure AI Foundry can group traces by conversation.
    """
    configurable = config.get("configurable", {})
    raw_config_media_id = configurable.get("media_id")
    raw_config_media_ids = configurable.get("media_ids")
    config_media_id, config_media_ids = normalize_media_selection(
        raw_config_media_id,
        raw_config_media_ids,
    )

    # --- OpenTelemetry conversation/user attribution ---
    thread_id = configurable.get("thread_id")
    user_id = state.get("user_id") or configurable.get("user_id")

    from agent.utils.observability import set_conversation_id, set_otel_user_id

    if thread_id and thread_id != "default":
        set_conversation_id(thread_id)
    if user_id:
        set_otel_user_id(user_id)

    # Also stamp directly on the current span (belt-and-suspenders)
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.is_recording():
            if thread_id and thread_id != "default":
                span.set_attribute("gen_ai.conversation.id", thread_id)
            if user_id:
                span.set_attribute("enduser.id", user_id)
    except Exception:  # noqa: S110
        pass  # OTel not available — safe to ignore

    raw_state_media_id = state.get("media_id")
    raw_state_media_ids = state.get("media_ids")
    state_media_id, state_media_ids = normalize_media_selection(
        raw_state_media_id,
        raw_state_media_ids,
    )

    updates: dict = {}
    if user_id and not state.get("user_id"):
        updates["user_id"] = user_id

    # Resolve effective media_id: config > state (checkpoint)
    effective_media_id = config_media_id or state_media_id
    effective_media_ids = config_media_ids or state_media_ids

    if effective_media_id and effective_media_id != raw_state_media_id:
        source = "config" if config_media_id else "checkpoint"
        logger.info(
            f"restore_media_context: overriding state media_id "
            f"'{raw_state_media_id}' → '{effective_media_id}' (source={source})"
        )
        updates["media_id"] = effective_media_id
        updates["video_context"] = VideoContext(media_id=effective_media_id)

    elif effective_media_id and not state.get("video_context"):
        # media_id is consistent but video_context is missing
        updates["video_context"] = VideoContext(media_id=effective_media_id)

    if effective_media_ids and effective_media_ids != raw_state_media_ids:
        updates["media_ids"] = effective_media_ids

    if effective_media_ids and len(effective_media_ids) > 1:
        logger.info(
            "restore_media_context: multi-video mode with %d videos: %s",
            len(effective_media_ids),
            effective_media_ids,
        )

    # Resolve video titles for multi-video mode
    if effective_media_ids and len(effective_media_ids) > 1:
        existing_titles = state.get("video_titles") or {}
        needs_resolution = any(mid not in existing_titles for mid in effective_media_ids)
        if needs_resolution:
            titles = _resolve_video_titles(effective_media_ids)
            updates["video_titles"] = titles
            logger.info(
                "restore_media_context: resolved video titles: %s",
                {mid: titles.get(mid, "?") for mid in effective_media_ids},
            )

    # Fallback: parse QPRISMA_CONTEXT/QPRISMA_BENCH envelopes embedded in the
    # first message (used by the Video-MME evaluation pipeline).
    if not effective_media_id:
        _extract_message_envelopes(state.get("messages") or [], updates)

    if updates:
        logger.info(f"restore_media_context: applying updates {list(updates.keys())}")
    else:
        logger.debug(f"restore_media_context: no updates needed (media_id={effective_media_id!r})")

    return updates


def get_system_message(state: AgentState) -> SystemMessage:
    """Build system message based on video context and conversation history."""
    video_context = state.get("video_context")
    media_id = state.get("media_id")
    media_ids = state.get("media_ids")
    normalized_media_id, normalized_media_ids = normalize_media_selection(media_id, media_ids)
    media_id = normalized_media_id
    media_ids = normalized_media_ids
    conversation_context = state.get("conversation_context", [])

    # Determine mode: multi-video, single-video, or no video
    is_multi_video = media_ids and len(media_ids) > 1
    has_video = is_multi_video or (video_context and video_context.get("media_id")) or media_id

    if is_multi_video:
        content = MULTI_VIDEO_SYSTEM_PROMPT
        video_titles = state.get("video_titles") or {}
        video_lines = []
        for i, mid in enumerate(media_ids):
            title = video_titles.get(mid)
            if title:
                video_lines.append(f'  - Video {i + 1}: "{title}" (id: {mid})')
            else:
                video_lines.append(f"  - Video {i + 1}: {mid}")
        video_list = "\n".join(video_lines)
        content += f"\n\n**Selected Videos ({len(media_ids)}):**\n{video_list}"
        content += "\n\nUse `get_library_overview` first to understand what each video covers."
        content += "\nUse `search_across_videos` to search all videos at once."
        content += "\nUse `compare_videos` to compare content between videos."
        content += (
            "\nFor single-video queries, use `target_video_id` parameter "
            "to specify which video to analyze."
        )
    elif has_video:
        content = SYSTEM_PROMPT
        if video_context and video_context.get("title"):
            content += f"\n\n**Current Video:** {video_context.get('title')}"
        if video_context and video_context.get("duration"):
            from agent.utils.formatting import format_timestamp as fmt_ts

            duration = video_context.get("duration")
            content += f" (Duration: {fmt_ts(duration)})"
    else:
        content = NO_VIDEO_CONTEXT_PROMPT

    # Add conversation context for memory
    if conversation_context:
        content += f"\n\n**Previous Topics Discussed:** {', '.join(conversation_context[-5:])}"

    if is_letter_only_benchmark(state.get("benchmark_context")):
        content += (
            "\n\n## Benchmark Response Mode\n"
            "This is a multiple-choice video benchmark. Use the available video tools "
            "to inspect the selected video before answering. The final response must "
            "be exactly one uppercase letter: A, B, C, or D. Do not include "
            "explanations, citations, markdown, or follow-up questions."
        )

    return SystemMessage(content=content)


async def call_model(state: AgentState, config: RunnableConfig) -> dict:
    """
    Call the LLM node.

    Invokes the model with current messages and available tools.
    Uses message trimming to prevent context window overflow.
    Returns updated messages with AI response.
    """
    video_context = state.get("video_context")
    media_id = state.get("media_id")
    media_ids = state.get("media_ids")
    normalized_media_id, normalized_media_ids = normalize_media_selection(media_id, media_ids)
    media_id = normalized_media_id
    media_ids = normalized_media_ids or media_ids

    # Defense-in-depth: fall back to config if state lost media_id
    if not media_id:
        configurable = config.get("configurable", {})
        config_media_id, config_media_ids = normalize_media_selection(
            configurable.get("media_id"),
            configurable.get("media_ids"),
        )
        media_id = config_media_id or media_id
        media_ids = config_media_ids or media_ids
        if media_id:
            logger.info(f"call_model: recovered media_id from config: {media_id}")
    if not media_ids:
        configurable = config.get("configurable", {})
        media_ids = configurable.get("media_ids") or media_ids

    is_multi_video = media_ids and len(media_ids) > 1
    has_video = is_multi_video or (video_context and video_context.get("media_id")) or media_id

    logger.info(f"call_model: media_id={media_id}, media_ids={media_ids}, has_video={has_video}")

    # Get tools - use dynamic binding if enabled
    tools = []
    if has_video:
        # Get user query for dynamic tool selection
        messages = state.get("messages", [])
        user_query = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.type == "human":
                user_query = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        # Dynamic tool binding - select focused subset
        if user_query:
            tools = select_tools_for_query(
                user_query, SEARCH_TOOLS, max_tools=8, is_multi_video=bool(is_multi_video)
            )
        else:
            tools = SEARCH_TOOLS

        logger.info(f"call_model: selected {len(tools)} tools for query: '{user_query[:50]}...'")
    else:
        logger.warning("call_model: NO VIDEO CONTEXT - tools will be empty!")

    system_message = get_system_message(state)

    return await base_call_model(
        state=state,
        config=config,
        tools=tools,
        system_message=system_message,
        max_iterations=MAX_TOOL_ITERATIONS,
        warn_iterations=WARN_TOOL_ITERATIONS,
        temperature=settings.azure.openai_agent_temperature,
    )


async def update_context(state: AgentState, config: RunnableConfig) -> dict:
    """
    Update conversation context after tool execution.

    Extracts key topics and entities from the conversation
    to maintain context awareness across turns.
    """
    return await update_context_node(state, config)


def should_continue(state: AgentState) -> Literal["tools", "error_handler", "__end__"]:
    """
    Determine if the agent should continue or end.

    Returns:
        "tools": If there are tool calls to execute
        "error_handler": If error threshold reached with partial results
        "__end__": If no tool calls or max iterations exceeded

    Checks:
    1. If there are tool calls to execute
    2. If we've exceeded max iterations
    3. If error threshold reached
    """
    return base_should_continue(state, max_iterations=MAX_TOOL_ITERATIONS)
