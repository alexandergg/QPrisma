"""
Agent State Definition
======================

Defines the typed state for the video agent, following LangGraph patterns.
State flows through the agent graph and accumulates tool results.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict


class MessageRole(str, Enum):
    """Message roles in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentMessage(TypedDict, total=False):
    """A message in the agent conversation."""

    role: str  # system, user, assistant, tool
    content: str | None
    name: str | None  # Tool name for tool messages
    tool_call_id: str | None  # For tool responses
    tool_calls: list[dict] | None  # For assistant tool requests


class ToolCall(TypedDict):
    """A tool call requested by the LLM."""

    id: str
    type: str  # "function"
    function: dict  # {"name": str, "arguments": str}


class ToolResult(TypedDict):
    """Result of a tool execution."""

    tool_call_id: str
    tool_name: str
    result: Any
    error: str | None


class VideoContext(TypedDict, total=False):
    """Context about the current video being discussed."""

    media_id: str
    title: str | None
    duration: float | None
    chapters: list[dict] | None
    current_timestamp: float | None


class VideoAgentState(TypedDict, total=False):
    """
    Complete state for the video agent.

    Follows LangGraph's state pattern where each node can read/write state.
    Messages are accumulated using a reducer pattern.
    """

    # Conversation
    messages: list[AgentMessage]

    # Video context
    video_context: VideoContext | None

    # Current turn
    pending_tool_calls: list[ToolCall]
    tool_results: list[ToolResult]

    # Control flow
    should_continue: bool
    iteration_count: int
    max_iterations: int

    # Output
    final_response: str | None
    sources: list[dict]

    # Metadata
    user_id: str | None
    session_id: str | None


@dataclass
class AgentConfig:
    """Configuration for the video agent."""

    # Model settings - uses AZURE_OPENAI_DEPLOYMENT_GPT env var
    model_deployment: str | None = None  # Will be set from env if None
    temperature: float = 0.7
    max_tokens: int = 1000

    # Agent behavior
    max_iterations: int = 5  # Max tool call loops
    enable_streaming: bool = True

    # Search settings
    search_limit: int = 10
    search_expansion_hops: int = 1
    use_reranking: bool = True

    # Memory
    max_history_messages: int = 20
    enable_memory: bool = True


def create_initial_state(
    message: str,
    media_id: str | None = None,
    chat_history: list[dict] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> VideoAgentState:
    """
    Create initial state for a new agent invocation.

    Args:
        message: User's message
        media_id: Optional video ID for context
        chat_history: Previous conversation messages
        user_id: User identifier
        session_id: Session identifier for memory

    Returns:
        Initial VideoAgentState
    """
    messages: list[AgentMessage] = []

    # Add chat history
    if chat_history:
        for msg in chat_history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

    # Add current user message
    messages.append({
        "role": "user",
        "content": message,
    })

    # Build video context if media_id provided
    video_context: VideoContext | None = None
    if media_id:
        video_context = {"media_id": media_id}

    return VideoAgentState(
        messages=messages,
        video_context=video_context,
        pending_tool_calls=[],
        tool_results=[],
        should_continue=True,
        iteration_count=0,
        max_iterations=5,
        final_response=None,
        sources=[],
        user_id=user_id,
        session_id=session_id,
    )
