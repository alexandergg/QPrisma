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
    base_call_model,
    base_should_continue,
    update_context_node,
    select_tools_for_query,
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_WARN_TOOL_ITERATIONS,
)
from agent.prompts import NO_VIDEO_CONTEXT_PROMPT, SYSTEM_PROMPT
from agent.state.agent_state import AgentState
from agent.tools import SEARCH_TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = DEFAULT_MAX_TOOL_ITERATIONS
WARN_TOOL_ITERATIONS = DEFAULT_WARN_TOOL_ITERATIONS


def get_system_message(state: AgentState) -> SystemMessage:
    """Build system message based on video context and conversation history."""
    video_context = state.get("video_context")
    media_id = state.get("media_id")
    conversation_context = state.get("conversation_context", [])

    # Check if we have video context (either from video_context dict or media_id field)
    has_video = (video_context and video_context.get("media_id")) or media_id

    if has_video:
        content = SYSTEM_PROMPT
        if video_context and video_context.get("title"):
            content += f"\n\n**Current Video:** {video_context.get('title')}"
        if video_context and video_context.get("duration"):
            from agent.utils.formatting import format_timestamp as fmt_ts
            duration = video_context.get("duration")
            content += f" (Duration: {fmt_ts(duration)})"
        
        # Add conversation context for memory
        if conversation_context:
            content += f"\n\n**Previous Topics Discussed:** {', '.join(conversation_context[-5:])}"
    else:
        content = NO_VIDEO_CONTEXT_PROMPT

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
    has_video = (video_context and video_context.get("media_id")) or media_id
    
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
            tools = select_tools_for_query(user_query, SEARCH_TOOLS, max_tools=8)
        else:
            tools = SEARCH_TOOLS
    
    system_message = get_system_message(state)
    
    return await base_call_model(
        state=state,
        config=config,
        tools=tools,
        system_message=system_message,
        max_iterations=MAX_TOOL_ITERATIONS,
        warn_iterations=WARN_TOOL_ITERATIONS,
        temperature=0.7,
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

