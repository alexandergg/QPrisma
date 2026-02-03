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

from langchain_core.messages import AnyMessage, ToolMessage, trim_messages
from langgraph.graph.message import add_messages

# Token limits for context management
MAX_CONTEXT_TOKENS = 200000  # Conservative limit below 272k for gpt-5
MAX_TOOL_RESULT_CHARS = 6000  # ~1500 tokens per tool result
CHARS_PER_TOKEN = 4  # Rough estimate


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text. Rough estimate: ~4 chars per token."""
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


def _token_counter(messages: list[AnyMessage]) -> int:
    """
    Count approximate tokens in message list.
    Used by trim_messages to prevent context overflow.
    """
    total = 0
    for msg in messages:
        # Message role/structure overhead
        total += 10
        
        # Content tokens
        content = msg.content if isinstance(msg.content, str) else str(msg.content) if msg.content else ""
        total += _estimate_tokens(content)
        
        # Tool calls overhead
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                total += _estimate_tokens(str(tc))
    
    return total


def _truncate_tool_message_content(msg: AnyMessage) -> AnyMessage:
    """Truncate tool message content if too large."""
    if not isinstance(msg, ToolMessage):
        return msg
    
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    
    if len(content) > MAX_TOOL_RESULT_CHARS:
        truncated = content[:MAX_TOOL_RESULT_CHARS] + "... [truncated for context limit]"
        # Create new ToolMessage with truncated content
        return ToolMessage(
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name if hasattr(msg, 'name') else None,
        )
    return msg


# Message trimmer to prevent context window overflow
def get_message_trimmer(max_tokens: int = 80000):
    """
    Create a message trimmer to prevent context window overflow.

    Args:
        max_tokens: Maximum tokens to keep in context (default 80k for safety margin)

    Returns:
        Configured trim_messages function
    """
    return trim_messages(
        max_tokens=max_tokens,
        strategy="last",
        token_counter=_token_counter,  # Use proper token estimation
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

    # Media ID - top-level for easy InjectedState access by tools
    media_id: str | None

    # Video context (for VideoAgent)
    video_context: VideoContext | None

    # Project context (for EditorAgent)
    project_context: ProjectContext | None
    project_id: str | None

    # Sources found during search
    sources: list[dict]

    # Planning and iteration tracking
    tool_calls_count: int  # Track number of tool calls made
    conversation_context: list[str]  # Key topics/entities discussed
    
    # Conversation summarization for long chats
    conversation_summary: str | None  # Summary of prior conversation turns
    total_turns: int  # Total conversation turns for summarization trigger

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
        media_id=media_id,
        video_context=video_context,
        project_context=project_context,
        project_id=project_id,
        sources=[],
        user_id=user_id,
        session_id=session_id,
    )
