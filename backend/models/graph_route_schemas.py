"""
Pydantic Request/Response Models for Knowledge Graph API Routes

These schemas define the structure of requests and responses for the
Knowledge Graph API endpoints in graph_routes.py.
"""

from pydantic import BaseModel, Field

from models.graph_models import EntityType, NodeType, RelationType

# =============================================================================
# Basic Graph Operations Models
# =============================================================================


class GraphHealthResponse(BaseModel):
    """Graph health check response."""

    status: str
    connected: bool
    uri: str
    message: str | None = None


class EntitySearchRequest(BaseModel):
    """Request for entity search."""

    query: str
    entity_types: list[EntityType] | None = None
    video_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FrameSearchRequest(BaseModel):
    """Request for frame search."""

    query: str
    video_id: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ContextExpansionRequest(BaseModel):
    """Request for context expansion."""

    node_id: str
    hops: int = Field(default=2, ge=1, le=4)
    relation_types: list[RelationType] | None = None
    max_nodes: int = Field(default=50, ge=1, le=200)


class ContextExpansionResponse(BaseModel):
    """Context expansion response."""

    center_node_id: str
    hops: int
    total_nodes: int
    nodes_by_distance: dict


class EntityTimelineRequest(BaseModel):
    """Request for entity timeline."""

    entity_name: str
    video_id: str


class EntityTimelineResponse(BaseModel):
    """Entity timeline response."""

    entity_name: str
    video_id: str
    occurrences: list[dict]
    total_occurrences: int


class RelatedEntitiesRequest(BaseModel):
    """Request for related entities."""

    entity_id: str
    relation_types: list[RelationType] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ProcessVideoGraphRequest(BaseModel):
    """Request to process the graph for a video."""

    video_id: str
    reprocess: bool = False
    include_semantic_relations: bool = True


class ProcessVideoGraphResponse(BaseModel):
    """Graph processing response."""

    video_id: str
    status: str
    message: str
    stats: dict | None = None


# =============================================================================
# Hybrid Search Models
# =============================================================================


class HybridSearchRequest(BaseModel):
    """Request for hybrid search (vector + graph + fulltext)."""

    query: str
    node_types: list[NodeType] | None = None
    video_id: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    limit: int = Field(default=20, ge=1, le=100)
    expansion_hops: int = Field(default=2, ge=1, le=4)
    use_reranking: bool = True


class CrossVideoSearchRequest(BaseModel):
    """Request for cross-video search."""

    reference_node_id: str
    limit: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)


class CrossVideoSearchResponse(BaseModel):
    """Cross-video search response."""

    reference_node_id: str
    similar_nodes: list[dict]
    total_found: int


# =============================================================================
# Embedding Management Models
# =============================================================================


class GenerateEmbeddingsRequest(BaseModel):
    """Request to generate embeddings in bulk."""

    node_type: NodeType
    video_id: str | None = None
    batch_size: int = Field(default=50, ge=1, le=200)


class GenerateEmbeddingsResponse(BaseModel):
    """Embedding generation response."""

    node_type: str
    embeddings_generated: int
    video_id: str | None = None


class EmbeddingStatsResponse(BaseModel):
    """Embedding service statistics."""

    total_requests: int
    cache_hits: int
    cache_hit_rate: float
    tokens_used: int


# =============================================================================
# Hierarchical Context Models
# =============================================================================


class ProcessHierarchyRequest(BaseModel):
    """Request to process the complete hierarchy of a video."""

    video_path: str
    video_id: str
    title: str | None = None
    fps: float = 30.0
    duration: float | None = None
    resolution: tuple[int, int] = (1920, 1080)


class ProcessHierarchyResponse(BaseModel):
    """Hierarchical processing response."""

    video_id: str
    status: str
    levels_processed: dict
    embeddings_generated: dict
    nodes_created: dict
    processing_time_seconds: float | None = None
    errors: list[str] = []


class DrillDownSearchRequest(BaseModel):
    """Request for hierarchical drill-down search."""

    query: str
    video_id: str | None = None
    start_level: str = Field(default="video", pattern="^(video|chapter|scene)$")
    target_level: str = Field(default="scene", pattern="^(video|chapter|scene|frame)$")
    top_k: int = Field(default=5, ge=1, le=20)
    include_context: bool = True


class HierarchyLevelResponse(BaseModel):
    """Representation of a level in the hierarchy."""

    level: str
    node_id: str
    node_type: str
    summary: str | None = None
    title: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    children_count: int = 0


class DrillDownSearchResponse(BaseModel):
    """Drill-down search response."""

    query: str
    results: list[dict]
    total_results: int
    levels_traversed: list[str]


class LoadChildrenRequest(BaseModel):
    """Request for lazy-loading children."""

    node_id: str
    node_type: NodeType
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class LoadChildrenResponse(BaseModel):
    """Lazy-load response."""

    parent_node_id: str
    children: list[HierarchyLevelResponse]
    total_children: int
    has_more: bool


class HierarchyStatsResponse(BaseModel):
    """Hierarchy statistics for a video."""

    video_id: str
    video_title: str | None = None
    duration_seconds: float | None = None
    hierarchy: dict
    embeddings: dict


class HierarchyPathResponse(BaseModel):
    """Path from the root to a node."""

    node_id: str
    path: list[HierarchyLevelResponse]
    depth: int
