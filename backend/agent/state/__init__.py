"""
Agent State
===========

LangGraph state definitions using TypedDict with Annotated reducers.

Includes Input/Output schema separation for clean API boundaries.
"""

from agent.state.agent_state import (
    # Core state types
    AgentState,
    AgentInputState,
    AgentOutputState,
    # Context types
    ProjectContext,
    VideoContext,
    # Metadata types
    SourceMetadata,
    NavigationAction,
    ClipSuggestion,
    EntityMention,
    # Factory
    create_agent_state,
    # Utilities
    get_message_trimmer,
    truncate_tool_message_content,
    # Constants
    MAX_CONTEXT_TOKENS,
    MAX_TOOL_RESULT_CHARS,
    # Retry policy helpers
    RetryableError,
    NonRetryableError,
    should_retry_exception,
    NON_RETRYABLE_EXCEPTIONS,
    RETRYABLE_EXCEPTIONS,
)

__all__ = [
    # Core state types
    "AgentState",
    "AgentInputState",
    "AgentOutputState",
    # Context types
    "ProjectContext",
    "VideoContext",
    # Metadata types
    "SourceMetadata",
    "NavigationAction",
    "ClipSuggestion",
    "EntityMention",
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
