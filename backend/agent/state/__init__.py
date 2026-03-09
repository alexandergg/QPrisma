"""
Agent State
===========

LangGraph state definitions using TypedDict with Annotated reducers.

Includes Input/Output schema separation for clean API boundaries.
"""

from agent.state.agent_state import (
    # Constants
    MAX_CONTEXT_TOKENS,
    MAX_TOOL_RESULT_CHARS,
    NON_RETRYABLE_EXCEPTIONS,
    RETRYABLE_EXCEPTIONS,
    AgentInputState,
    AgentOutputState,
    # Core state types
    AgentState,
    EntityMention,
    NavigationAction,
    NonRetryableError,
    # Retry policy helpers
    RetryableError,
    # Metadata types
    SourceMetadata,
    ToolArtifactRef,
    # Context types
    VideoContext,
    # Factory
    create_agent_state,
    # Utilities
    get_message_trimmer,
    should_retry_exception,
    truncate_tool_message_content,
)

__all__ = [
    # Core state types
    "AgentState",
    "AgentInputState",
    "AgentOutputState",
    # Context types
    "VideoContext",
    # Metadata types
    "SourceMetadata",
    "NavigationAction",
    "EntityMention",
    "ToolArtifactRef",
    # Factory
    "create_agent_state",
    # Utilities
    "get_message_trimmer",
    "truncate_tool_message_content",
    # Constants
    "MAX_CONTEXT_TOKENS",
    "MAX_TOOL_RESULT_CHARS",
    # Retry policy helpers
    "RetryableError",
    "NonRetryableError",
    "should_retry_exception",
    "NON_RETRYABLE_EXCEPTIONS",
    "RETRYABLE_EXCEPTIONS",
]
