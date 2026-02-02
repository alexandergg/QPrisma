"""
LangGraph State Definition
==========================

Typed state for the video agent using LangGraph patterns.
Uses Annotated types with reducers for message accumulation.

Best Practices:
- Uses add_messages reducer for automatic message accumulation
- Extends MessagesState pattern for compatibility
- Supports trim_messages for context window management
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, trim_messages
from langgraph.graph.message import add_messages


# Message trimmer to prevent context window overflow
def get_message_trimmer(max_tokens: int = 8000):
    """
    Create a message trimmer to prevent context window overflow.

    Args:
        max_tokens: Maximum tokens to keep in context

    Returns:
        Configured trim_messages function
    """
    return trim_messages(
        max_tokens=max_tokens,
        strategy="last",
        token_counter=len,  # Simple approximation; use tiktoken for accuracy
        include_system=True,
        allow_partial=False,
        start_on="human",
    )


class VideoContext(TypedDict, total=False):
    """Context about the current video being discussed."""

    media_id: str
    title: str | None
    duration: float | None
    chapters: list[dict] | None
    current_timestamp: float | None


class ProjectContext(TypedDict, total=False):
    """Context about the current editor project."""

    project_id: str
    project_name: str
    source_media_id: str
    video_title: str
    video_duration: float
    clips_count: int
    clips: list[dict]


class AgentState(TypedDict, total=False):
    """
    LangGraph state for the video agent.

    Uses Annotated with add_messages reducer for automatic message accumulation.
    Each node reads/writes to this state.
    """

    # Messages with reducer - LangGraph handles accumulation
    messages: Annotated[list[AnyMessage], add_messages]

    # Video context (for VideoAgent)
    video_context: VideoContext | None

    # Project context (for EditorAgent)
    project_context: ProjectContext | None
    project_id: str | None

    # Sources found during search
    sources: list[dict]

    # Metadata
    user_id: str | None
    session_id: str | None


class ConfigSchema(TypedDict, total=False):
    """Configuration schema for the graph."""

    model_deployment: str
    temperature: float
    max_tokens: int
    max_iterations: int


def create_agent_state(
    messages: list[AnyMessage],
    media_id: str | None = None,
    project_id: str | None = None,
    project_context: ProjectContext | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentState:
    """
    Create initial agent state.

    Args:
        messages: Initial messages (including user message)
        media_id: Optional video ID for context
        project_id: Optional project ID for editor
        project_context: Optional project context
        user_id: User identifier
        session_id: Session identifier for memory

    Returns:
        Initial AgentState
    """
    video_context: VideoContext | None = None
    if media_id:
        video_context = VideoContext(media_id=media_id)

    return AgentState(
        messages=messages,
        video_context=video_context,
        project_context=project_context,
        project_id=project_id,
        sources=[],
        user_id=user_id,
        session_id=session_id,
    )
