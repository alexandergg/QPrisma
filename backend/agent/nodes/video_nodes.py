"""
Video Agent Nodes
=================

Nodes for the LangGraph-based video agent.
Uses shared base implementation with video-specific configuration.
"""

import logging
from typing import Literal

from langchain_core.messages import SystemMessage
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


def restore_media_context(state: AgentState, config: RunnableConfig) -> dict:
    """
    Restore media_id from RunnableConfig on every graph invocation,
    falling back to the checkpointed state value.

    Priority order for resolving media_id:
    1. ``config.configurable["media_id"]`` — fresh value from the current request
    2. ``state["media_id"]`` — preserved from a previous invocation via checkpoint

    When ``create_agent_state()`` omits the ``media_id`` key (because the
    frontend didn't send one), LangGraph preserves the checkpointed value
    in ``state``.  This node ensures ``video_context`` stays in sync.
    """
    configurable = config.get("configurable", {})
    config_media_id = configurable.get("media_id")
    config_media_ids = configurable.get("media_ids")

    state_media_id = state.get("media_id")
    state_media_ids = state.get("media_ids")

    # Resolve effective media_id: config wins, then checkpoint state
    effective_media_id = config_media_id or state_media_id
    effective_media_ids = config_media_ids or state_media_ids

    updates: dict = {}

    if effective_media_id and effective_media_id != state_media_id:
        logger.info(
            f"restore_media_context: overriding state media_id "
            f"'{state_media_id}' → '{effective_media_id}' "
            f"(source={'config' if config_media_id else 'checkpoint'})"
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

    if updates:
        logger.info(f"restore_media_context: applying updates {list(updates.keys())}")
    else:
        logger.debug(
            f"restore_media_context: no updates needed " f"(media_id={effective_media_id!r})"
        )

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
        video_list = "\n".join(f"  - Video {i+1}: {mid}" for i, mid in enumerate(media_ids))
        content += f"\n\n**Selected Videos ({len(media_ids)}):**\n{video_list}"
        content += "\n\nUse `search_across_videos` to search all videos at once."
        content += "\nUse `compare_videos` to compare content between videos."
        content += "\nFor single-video queries, the primary video (first selected) is used."
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

    logger.info(
        f"call_model: media_id={media_id}, " f"media_ids={media_ids}, has_video={has_video}"
    )

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
