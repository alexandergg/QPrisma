"""
API Request/Response Schemas for QPrisma.

This module consolidates Pydantic models used across API routes
for better reusability and maintainability.
"""

from enum import Enum

from pydantic import BaseModel, Field

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
# Search Schemas
# =============================================================================


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
    # Search
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
