"""
API Request/Response Schemas for QPrisma.

This module consolidates Pydantic models used across API routes
for better reusability and maintainability.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field
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


class EntityReference(TypedDict, total=False):
    """Structure for entity references in responses."""

    name: str
    type: str  # person, organization, location, topic, etc.
    confidence: float
    mentions: list[float]  # timestamps where mentioned
    description: str | None


class TokenUsage(TypedDict, total=False):
    """Structure for token usage tracking."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None


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


class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2)


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Authentication token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 hours


class UserResponse(BaseModel):
    """User profile response."""

    id: str
    email: str
    name: str


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


class AgentChatRequest(BaseModel):
    """Agent chat request with tool calling."""

    message: str
    media_id: str | None = None
    media_ids: list[str] | None = Field(default=None, max_length=10)
    chat_history: list[ChatHistoryMessage] | None = None
    session_id: str | None = None
    output_format: Literal["markdown", "json", "structured"] = Field(
        default="markdown",
        description="Response format: 'markdown' (default), 'json', or 'structured'",
    )

    def get_effective_media_ids(self) -> list[str]:
        """Merge media_id and media_ids into a deduplicated list."""
        ids: list[str] = []
        if self.media_id:
            ids.append(self.media_id)
        if self.media_ids:
            ids.extend(self.media_ids)
        seen: set[str] = set()
        result: list[str] = []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                result.append(mid)
        return result[:10]


class VideoSource(BaseModel):
    """A source reference in the video."""

    timestamp: float
    timestamp_formatted: str
    type: Literal[
        "visual",
        "audio",
        "entity",
        "scene",
        "visible",
        "comparison",
        "cross_video",
        "highlight",
        "unknown",
    ] = "visual"
    description: str
    score: float = 0.0
    thumbnail_url: str | None = None
    frame_id: str | None = None
    media_id: str | None = None
    video_title: str | None = None


class NavigationAction(BaseModel):
    """A suggested navigation action for the UI."""

    action: Literal["jump_to", "create_clip", "explore", "compare"]
    label: str
    timestamp: float | None = None
    end_timestamp: float | None = None
    parameters: dict[str, Any] | None = None


class SuggestedQuestion(BaseModel):
    """A suggested follow-up question."""

    question: str
    category: Literal["related", "deeper", "compare", "explore", "entity", "timeline"] = "related"


class AgentChatResponse(BaseModel):
    """Enhanced agent chat response with rich metadata."""

    response: str
    sources: list[VideoSource] = Field(default_factory=list)
    tool_calls_made: int = 0
    session_id: str | None = None

    # New fields for enhanced UX
    navigation_actions: list[NavigationAction] = Field(
        default_factory=list, description="Suggested UI actions like seeking to timestamps"
    )
    suggested_questions: list[SuggestedQuestion] = Field(
        default_factory=list, description="Follow-up questions the user might want to ask"
    )
    clip_suggestions: list[NavigationAction] = Field(
        default_factory=list, description="Exportable clip time ranges found"
    )
    entities_mentioned: list[EntityReference] = Field(
        default_factory=list, description="Entities referenced in the response"
    )
    token_usage: TokenUsage | None = Field(
        default=None, description="Token consumption for this request"
    )


# =============================================================================
# Batch Processing Schemas
# =============================================================================


class BatchStatusResponse(BaseModel):
    """Batch job status."""

    azure_batch_id: str
    status: str
    total_requests: int
    completed_requests: int
    failed_requests: int
    progress_percent: float
    estimated_cost: float | None = None
    created_at: str | None = None
    completed_at: str | None = None


class CostEstimateResponse(BaseModel):
    """Cost estimate for batch processing."""

    frame_count: int
    estimated_tokens: int
    estimated_cost_usd: float
    savings_vs_regular_usd: float


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


class ProcessingConfig(BaseModel):
    """Processing configuration for a job."""

    extract_frames: bool = True
    transcribe_audio: bool = True
    analyze_frames: bool = True
    build_graph: bool = True
    frame_interval: float = 1.0
    max_frames: int = 100
    use_batch_api: bool = True
    priority: str = "normal"


class JobSubmitRequest(BaseModel):
    """Job submission request."""

    media_id: str
    config: ProcessingConfig | None = None
    callback_url: str | None = None


class JobSubmitResponse(BaseModel):
    """Job submission response."""

    job_id: str
    media_id: str
    status: JobStatus
    message: str
    estimated_time_seconds: int | None = None


class JobStatusResponse(BaseModel):
    """Job status response."""

    job_id: str
    media_id: str
    status: JobStatus
    progress: float = 0.0
    current_step: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobListResponse(BaseModel):
    """List of jobs response."""

    jobs: list[JobStatusResponse]
    total: int
    page: int
    page_size: int


# =============================================================================
# Graph Schemas
# =============================================================================


class GraphHealthResponse(BaseModel):
    """Graph database health check response."""

    connected: bool
    node_count: int = 0
    relationship_count: int = 0
    error: str | None = None


class EntitySearchRequest(BaseModel):
    """Entity search request."""

    query: str
    entity_type: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    video_id: str | None = None


class FrameSearchRequest(BaseModel):
    """Frame search request."""

    query: str
    video_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)


class ContextExpansionRequest(BaseModel):
    """Context expansion request."""

    node_id: str
    depth: int = Field(default=2, ge=1, le=5)
    include_embeddings: bool = False


class ContextExpansionResponse(BaseModel):
    """Context expansion response."""

    center_node: dict[str, Any]
    related_nodes: list[dict[str, Any]]
    relationships: list[dict[str, Any]]


class EntityTimelineRequest(BaseModel):
    """Entity timeline request."""

    entity_name: str
    video_id: str | None = None


class EntityTimelineResponse(BaseModel):
    """Entity timeline response."""

    entity_name: str
    occurrences: list[dict[str, Any]]
    total_duration: float


class RelatedEntitiesRequest(BaseModel):
    """Related entities request."""

    entity_name: str
    relation_types: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ProcessVideoGraphRequest(BaseModel):
    """Process video to graph request."""

    video_id: str
    include_entities: bool = True
    include_relations: bool = True


class ProcessVideoGraphResponse(BaseModel):
    """Process video to graph response."""

    video_id: str
    nodes_created: int
    relationships_created: int
    processing_time_ms: int


class HybridSearchRequest(BaseModel):
    """Hybrid search request combining vector + graph."""

    query: str
    video_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    graph_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class GenerateEmbeddingsRequest(BaseModel):
    """Generate embeddings request."""

    video_id: str
    node_types: list[str] | None = None
    overwrite: bool = False


class GenerateEmbeddingsResponse(BaseModel):
    """Generate embeddings response."""

    video_id: str
    embeddings_generated: int
    processing_time_ms: int


class CrossVideoSearchRequest(BaseModel):
    """Cross-video search request."""

    query: str
    limit: int = Field(default=20, ge=1, le=100)
    video_ids: list[str] | None = None


class CrossVideoSearchResponse(BaseModel):
    """Cross-video search response."""

    query: str
    results: list[dict[str, Any]]
    videos_searched: int


class EmbeddingStatsResponse(BaseModel):
    """Embedding statistics response."""

    total_embeddings: int
    by_node_type: dict[str, int]
    average_dimension: int
    coverage_percent: float


class ProcessHierarchyRequest(BaseModel):
    """Process hierarchical structure request."""

    video_id: str
    generate_summaries: bool = True
    generate_embeddings: bool = True
    min_scene_duration: float = 5.0


class ProcessHierarchyResponse(BaseModel):
    """Process hierarchical structure response."""

    video_id: str
    scenes_created: int
    chapters_created: int
    summaries_generated: int
    embeddings_generated: int
    processing_time_ms: int


class DrillDownSearchRequest(BaseModel):
    """Drill-down search request."""

    query: str
    video_id: str
    start_level: str = "video"  # video, chapter, scene, frame
    max_depth: int = Field(default=3, ge=1, le=4)
    limit_per_level: int = Field(default=5, ge=1, le=20)


class HierarchyLevelResponse(BaseModel):
    """Hierarchy level in drill-down response."""

    level: str
    node_id: str
    content: dict[str, Any]
    score: float
    children_count: int


class DrillDownSearchResponse(BaseModel):
    """Drill-down search response."""

    query: str
    levels: list[list[HierarchyLevelResponse]]
    total_results: int


class LoadChildrenRequest(BaseModel):
    """Load children nodes request."""

    parent_id: str
    parent_type: str
    limit: int = Field(default=10, ge=1, le=50)


class LoadChildrenResponse(BaseModel):
    """Load children nodes response."""

    parent_id: str
    children: list[dict[str, Any]]
    has_more: bool


class HierarchyStatsResponse(BaseModel):
    """Hierarchy statistics response."""

    video_id: str
    total_scenes: int
    total_chapters: int
    total_frames: int
    average_scene_duration: float


class HierarchyPathResponse(BaseModel):
    """Hierarchy path response."""

    node_id: str
    path: list[dict[str, Any]]
    depth: int


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
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "UserResponse",
    # Chat
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "AgentChatRequest",
    "AgentChatResponse",
    # Batch
    "BatchStatusResponse",
    "CostEstimateResponse",
    # Jobs
    "JobStatus",
    "ProcessingConfig",
    "JobSubmitRequest",
    "JobSubmitResponse",
    "JobStatusResponse",
    "JobListResponse",
    # Graph
    "GraphHealthResponse",
    "EntitySearchRequest",
    "FrameSearchRequest",
    "ContextExpansionRequest",
    "ContextExpansionResponse",
    "EntityTimelineRequest",
    "EntityTimelineResponse",
    "RelatedEntitiesRequest",
    "ProcessVideoGraphRequest",
    "ProcessVideoGraphResponse",
    "HybridSearchRequest",
    "GenerateEmbeddingsRequest",
    "GenerateEmbeddingsResponse",
    "CrossVideoSearchRequest",
    "CrossVideoSearchResponse",
    "EmbeddingStatsResponse",
    "ProcessHierarchyRequest",
    "ProcessHierarchyResponse",
    "DrillDownSearchRequest",
    "HierarchyLevelResponse",
    "DrillDownSearchResponse",
    "LoadChildrenRequest",
    "LoadChildrenResponse",
    "HierarchyStatsResponse",
    "HierarchyPathResponse",
    # Storage
    "ChangeTierRequest",
    "RehydrateRequest",
    "LifecyclePolicyRequest",
    # Processing
    "ProcessingSearchRequest",
    "EnhancedSearchRequest",
]
