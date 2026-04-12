"""
Video Agent Nodes
=================

Nodes for the LangGraph-based video agent.
Uses shared base implementation with video-specific configuration.
"""

import json
import logging
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

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = DEFAULT_MAX_TOOL_ITERATIONS
WARN_TOOL_ITERATIONS = DEFAULT_WARN_TOOL_ITERATIONS


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


# Defense-in-depth parser for QPRISMA_CONTEXT prefix.  Uses
# json.JSONDecoder.raw_decode() to handle nested JSON correctly
# (e.g. media_ids arrays) without regex fragility.
_CONTEXT_PREFIX = "[QPRISMA_CONTEXT:"
_json_decoder = json.JSONDecoder()


def _parse_qprisma_context_from_messages(
    messages: list,
) -> tuple[dict, list | None]:
    """Extract ``[QPRISMA_CONTEXT:{...}]`` from the last HumanMessage.

    Returns:
        (metadata_dict, updated_messages) — if a prefix was found and stripped.
        ({}, None) — if no prefix found (messages unchanged).
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            text = msg.content
            if not text.startswith(_CONTEXT_PREFIX):
                break  # only check the last HumanMessage

            json_start = len(_CONTEXT_PREFIX)
            try:
                metadata, json_end = _json_decoder.raw_decode(text, json_start)
            except (json.JSONDecodeError, ValueError):
                return {}, None

            if not isinstance(metadata, dict):
                return {}, None

            # Expect closing ']' after JSON
            if json_end >= len(text) or text[json_end] != "]":
                return {}, None

            rest_start = json_end + 1
            if rest_start < len(text) and text[rest_start] == "\n":
                rest_start += 1

            new_messages = list(messages)
            new_messages[i] = HumanMessage(content=text[rest_start:])
            return metadata, new_messages
    return {}, None


def restore_media_context(state: AgentState, config: RunnableConfig) -> dict:
    """
    Restore media_id from RunnableConfig on every graph invocation,
    falling back to the checkpointed state value.

    Priority order for resolving media_id:
    1. ``config.configurable["media_id"]`` — fresh value from the current request
    2. ``state["media_id"]`` — set by QPrismaStateConverter or checkpoint
    3. ``[QPRISMA_CONTEXT:...]`` parsed from messages — defense-in-depth fallback

    When ``create_agent_state()`` omits the ``media_id`` key (because the
    frontend didn't send one), LangGraph preserves the checkpointed value
    in ``state``.  This node ensures ``video_context`` stays in sync.

    In multi-video mode, also resolves human-readable video titles from the
    database so the system prompt can display them.

    Also stamps OpenTelemetry span attributes (``gen_ai.conversation.id``,
    ``enduser.id``) so Azure AI Foundry can group traces by conversation.
    """
    configurable = config.get("configurable", {})
    config_media_id = configurable.get("media_id")
    config_media_ids = configurable.get("media_ids")

    # --- OpenTelemetry conversation/user attribution ---
    thread_id = configurable.get("thread_id")
    user_id = state.get("user_id")

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

    state_media_id = state.get("media_id")
    state_media_ids = state.get("media_ids")

    # --- Defense-in-depth: parse QPRISMA_CONTEXT from messages ----------
    # Always attempt to strip QPRISMA_CONTEXT so it cannot leak into the LLM
    # prompt, even if state already has a media_id from a checkpoint.
    msg_media_id = None
    msg_media_ids = None
    updates: dict = {}

    messages = state.get("messages", [])
    msg_ctx, cleaned_messages = _parse_qprisma_context_from_messages(messages)
    if msg_ctx:
        msg_media_id = msg_ctx.get("media_id")
        msg_media_ids = msg_ctx.get("media_ids")
        msg_user_id = msg_ctx.get("user_id")
        if msg_user_id and not user_id:
            updates["user_id"] = msg_user_id
        if cleaned_messages is not None:
            updates["messages"] = cleaned_messages
        logger.info(
            "restore_media_context: extracted QPRISMA_CONTEXT from messages — "
            "media_id=%s, media_ids=%s",
            msg_media_id,
            msg_media_ids,
        )

    # Resolve effective media_id: config > message > state (converter/checkpoint)
    effective_media_id = config_media_id or msg_media_id or state_media_id
    effective_media_ids = config_media_ids or msg_media_ids or state_media_ids

    if effective_media_id and effective_media_id != state_media_id:
        source = "config" if config_media_id else "message" if msg_media_id else "checkpoint"
        logger.info(
            f"restore_media_context: overriding state media_id "
            f"'{state_media_id}' → '{effective_media_id}' (source={source})"
        )
        updates["media_id"] = effective_media_id
        updates["video_context"] = VideoContext(media_id=effective_media_id)

    elif effective_media_id and not state.get("video_context"):
        # media_id is consistent but video_context is missing
        updates["video_context"] = VideoContext(media_id=effective_media_id)

    if effective_media_ids and effective_media_ids != state_media_ids:
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

    # Defense-in-depth: fall back to config if state lost media_id
    if not media_id:
        configurable = config.get("configurable", {})
        media_id = configurable.get("media_id") or media_id
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
        temperature=1,
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
