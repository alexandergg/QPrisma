"""
API Request/Response Schemas for QPrisma.

This module consolidates Pydantic models used across API routes
for better reusability and maintainability.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# =============================================================================
# TypedDict Definitions (for structured dict typing)
# =============================================================================


class ChatHistoryMessage(TypedDict, total=False):
    """Structure for chat history messages."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str | None
    tool_calls: list[dict[str, Any]] | None


class SourceReference(TypedDict, total=False):
    """Structure for source references."""

    timestamp: float
    type: str  # visual, audio, entity, scene
    content: str
    score: float
    frame_id: str | None


# =============================================================================
# Authentication Schemas
# =============================================================================


class UserResponse(BaseModel):
    """User profile response."""

    id: str
    email: str
    name: str


class AuthConfigResponse(BaseModel):
    """Entra ID configuration for the frontend MSAL setup."""

    tenant_id: str
    client_id: str
    api_scope: str


# =============================================================================
# Chat Schemas
# =============================================================================


class ChatMessage(BaseModel):
    """A single chat message."""

    role: Literal["user", "assistant"] = Field(..., description="Message role")
    content: str


class ChatRequest(BaseModel):
    """Chat request with optional video context."""

    message: str
    media_id: str | None = None
    media_ids: list[str] | None = Field(default=None, max_length=10)
    chat_history: list[ChatHistoryMessage] | None = None

    def get_effective_media_ids(self) -> list[str]:
        """Merge media_id and media_ids into a deduplicated list."""
        ids: list[str] = []
        if self.media_id:
            ids.append(self.media_id)
        if self.media_ids:
            ids.extend(self.media_ids)
        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                result.append(mid)
        return result[:10]


class ChatResponse(BaseModel):
    """Chat response with sources."""

    response: str
    sources: list[SourceReference] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Video content search request."""

    query: str
    media_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    """A single search result."""

    timestamp: float
    content: str
    score: float
    type: str = "visual"  # visual or audio


class SearchResponse(BaseModel):
    """Search response with results."""

    query: str
    results: list[SearchResult]
    total: int


# =============================================================================
# Jobs Schemas
# =============================================================================


class JobStatus(str, Enum):
    """Job status enum."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# =============================================================================
# Storage Schemas
# =============================================================================


class ChangeTierRequest(BaseModel):
    """Change storage tier request."""

    blob_name: str
    target_tier: str  # hot, cool, cold, archive


class RehydrateRequest(BaseModel):
    """Rehydrate blob request."""

    blob_name: str
    priority: str = "standard"  # standard, high


class LifecyclePolicyRequest(BaseModel):
    """Lifecycle policy request."""

    days_to_cool: int = 30
    days_to_archive: int = 90
    days_to_delete: int | None = None


# =============================================================================
# Processing Schemas
# =============================================================================


class ProcessingSearchRequest(BaseModel):
    """Request for global search in processing routes."""

    query: str
    media_type: str | None = None
    top: int = 5


class EnhancedSearchRequest(BaseModel):
    """Enhanced search with re-ranking."""

    query: str
    media_id: str | None = None
    top_k: int = 20
    use_reranking: bool = True
    expand_query: bool = True


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Auth
    "UserResponse",
    "AuthConfigResponse",
    # Chat
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    # Jobs
    "JobStatus",
    # Storage
    "ChangeTierRequest",
    "RehydrateRequest",
    "LifecyclePolicyRequest",
    # Processing
    "ProcessingSearchRequest",
    "EnhancedSearchRequest",
]
