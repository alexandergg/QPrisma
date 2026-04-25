"""
LangGraph State Definition
==========================

Typed state for the video agent using LangGraph patterns.
Uses Annotated types with reducers for message accumulation.

Best Practices (LangGraph v1.0+):
- Input/Output schema separation to hide internal state from API consumers
- Uses add_messages reducer for automatic message accumulation
- Extends MessagesState pattern for compatibility
- Supports trim_messages for context window management
- Multi-tenant security via user_id scoping
"""

import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, ToolMessage, trim_messages
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

# Token limits for context management
MAX_CONTEXT_TOKENS = 200000  # Conservative limit below 272k for gpt-5
MAX_TOOL_RESULT_CHARS = 6000  # ~1500 tokens per tool result
CHARS_PER_TOKEN = 4  # Rough estimate (~20-30% margin vs tiktoken)


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
        content = (
            msg.content if isinstance(msg.content, str) else str(msg.content) if msg.content else ""
        )
        total += _estimate_tokens(content)

        # Tool calls overhead
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                total += _estimate_tokens(str(tc))

    return total


def truncate_tool_message_content(msg: AnyMessage) -> AnyMessage:
    """Truncate tool message content if too large."""
    if not isinstance(msg, ToolMessage):
        return msg

    content = msg.content if isinstance(msg.content, str) else str(msg.content)

    if len(content) > MAX_TOOL_RESULT_CHARS:
        truncated = content[:MAX_TOOL_RESULT_CHARS] + "... [truncated for context limit]"
        return ToolMessage(
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name if hasattr(msg, "name") else None,
        )
    return msg


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
        token_counter=_token_counter,
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


class AgentState(TypedDict, total=False):
    """
    LangGraph internal state for the video agent.

    Uses Annotated with add_messages reducer for automatic message accumulation.
    Each node reads/writes to this state.

    NOTE: This is the INTERNAL state. Use AgentInputState for graph input
    and AgentOutputState for graph output to hide internal bookkeeping.
    """

    # Messages with reducer - LangGraph handles accumulation
    messages: Annotated[list[AnyMessage], add_messages]

    # Media ID - top-level for easy InjectedState access by tools
    media_id: str | None

    # Multiple media IDs for cross-video analysis
    media_ids: list[str] | None

    # Mapping of media_id → human-readable title (populated in multi-video mode)
    video_titles: dict[str, str] | None

    # Video context (for VideoAgent)
    video_context: VideoContext | None

    # Sources found during search
    sources: list[dict]

    # Iteration tracking (INTERNAL - hidden from API consumers)
    tool_calls_count: int
    conversation_context: list[str]  # Key topics/entities discussed (bounded to 10)

    # Error tracking (INTERNAL - for graceful degradation)
    consecutive_errors: int
    last_error: str | None
    partial_results: list[dict]  # Results gathered before errors
    memory_context: list[str]  # Compact memory snippets from tool outputs
    artifact_refs: list[dict]  # References to full tool outputs stored externally

    # Metadata
    user_id: str | None
    session_id: str | None
    benchmark_context: dict | None


# =============================================================================
# Input/Output Schema Separation (LangGraph v1.0+ Best Practice)
# =============================================================================


class AgentInputState(TypedDict, total=False):
    """
    Input schema for the agent graph.

    This is what API consumers provide - clean and simple.
    Internal bookkeeping fields (tool_calls_count, etc.) are hidden.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    media_id: str | None
    media_ids: list[str] | None
    video_titles: dict[str, str] | None
    video_context: VideoContext | None
    user_id: str | None
    session_id: str | None
    benchmark_context: dict | None


class AgentOutputState(TypedDict, total=False):
    """
    Output schema for the agent graph.

    This is what API consumers receive - only relevant results.
    Internal bookkeeping fields are excluded.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    sources: list[dict]
    # Expose these for user context but not internal tracking
    video_context: VideoContext | None


def create_agent_state(
    messages: list[AnyMessage],
    media_id: str | None = None,
    media_ids: list[str] | None = None,
    video_titles: dict[str, str] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AgentState:
    """
    Create initial agent state.

    Args:
        messages: Initial messages (including user message)
        media_id: Optional video ID for context (single-video mode)
        media_ids: Optional list of video IDs for cross-video analysis
        video_titles: Optional mapping of media_id → title for display
        user_id: User identifier
        session_id: Session identifier for memory

    Returns:
        Initial AgentState
    """
    # Merge media_id and media_ids into a single deduplicated list
    effective_ids: list[str] = []
    if media_id:
        effective_ids.append(media_id)
    if media_ids:
        effective_ids.extend(media_ids)
    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for mid in effective_ids:
        if mid not in seen:
            seen.add(mid)
            deduped.append(mid)
    effective_ids = deduped[:10]

    # For backward compatibility, media_id is the first ID (or None)
    primary_media_id = effective_ids[0] if effective_ids else None

    logger.info(
        f"create_agent_state: media_id='{primary_media_id}', "
        f"media_ids={effective_ids}, session_id='{session_id}'"
    )

    # Build the state dict.  InjectedState fields (media_id, media_ids,
    # user_id, session_id) MUST always be present — even as None / [] —
    # because LangGraph's ToolNode does state["field"] (not .get()),
    # raising KeyError when the key is absent.
    state: dict = {
        "messages": messages,
        "sources": [],
        "tool_calls_count": 0,
        "conversation_context": [],
        "consecutive_errors": 0,
        "last_error": None,
        "partial_results": [],
        "memory_context": [],
        "artifact_refs": [],
        # InjectedState targets — always present to avoid KeyError
        "media_id": primary_media_id,
        "media_ids": effective_ids or [],
        "video_titles": video_titles or {},
        "user_id": user_id,
        "session_id": session_id,
    }

    if primary_media_id:
        state["video_context"] = VideoContext(media_id=primary_media_id)

    return state  # type: ignore[return-value]


# =============================================================================
# Retry Policy Configuration (LangGraph v1.0+ Best Practice)
# =============================================================================


class RetryableError(Exception):
    """Errors that should trigger retry (transient failures)."""

    pass


class NonRetryableError(Exception):
    """Errors that should NOT trigger retry (auth, validation, etc.)."""

    pass


# Exceptions that should NOT be retried
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,  # Validation errors
    TypeError,  # Type errors
    KeyError,  # Missing keys
    PermissionError,  # Auth errors
    NonRetryableError,  # Explicit non-retryable
)

# Exceptions that SHOULD be retried
RETRYABLE_EXCEPTIONS = (
    ConnectionError,  # Network issues
    TimeoutError,  # Timeouts
    RetryableError,  # Explicit retryable
    OSError,  # I/O errors (often transient)
)


def should_retry_exception(exc: Exception) -> bool:
    """
    Determine if an exception should trigger a retry.

    Per-exception retry policy - only retry transient errors,
    fail fast on auth/validation errors.
    """
    # Never retry explicit non-retryable errors
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False

    # Always retry explicit retryable errors
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True

    # Check error message for common transient patterns
    error_msg = str(exc).lower()
    transient_patterns = [
        "rate limit",
        "timeout",
        "connection",
        "temporarily unavailable",
        "503",
        "429",
        "retry",
    ]

    return any(pattern in error_msg for pattern in transient_patterns)
