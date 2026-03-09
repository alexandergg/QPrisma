"""
Agent Nodes
===========

LangGraph node implementations for the video agent.
Uses shared base implementation for DRY code.
"""

from agent.nodes.base import (
    # Constants
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_WARN_TOOL_ITERATIONS,
    MAX_CONSECUTIVE_ERRORS,
    # Shared utilities
    create_model,
    error_handler_node,
    select_tools_for_query,
    update_context_node,
)
from agent.nodes.video_nodes import (
    MAX_TOOL_ITERATIONS,
    WARN_TOOL_ITERATIONS,
    call_model,
    get_system_message,
    should_continue,
    update_context,
)

__all__ = [
    # Base utilities
    "create_model",
    "select_tools_for_query",
    "error_handler_node",
    "update_context_node",
    # Constants
    "DEFAULT_MAX_TOOL_ITERATIONS",
    "DEFAULT_WARN_TOOL_ITERATIONS",
    "MAX_CONSECUTIVE_ERRORS",
    # Video nodes
    "call_model",
    "should_continue",
    "update_context",
    "get_system_message",
    "MAX_TOOL_ITERATIONS",
    "WARN_TOOL_ITERATIONS",
]
