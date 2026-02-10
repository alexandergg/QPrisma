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
    """Respuesta de health check del grafo."""

    status: str
    connected: bool
    uri: str
    message: str | None = None


class EntitySearchRequest(BaseModel):
    """Request para búsqueda de entidades."""

    query: str
    entity_types: list[EntityType] | None = None
    video_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FrameSearchRequest(BaseModel):
    """Request para búsqueda en frames."""

    query: str
    video_id: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ContextExpansionRequest(BaseModel):
    """Request para expansión de contexto."""

    node_id: str
    hops: int = Field(default=2, ge=1, le=4)
    relation_types: list[RelationType] | None = None
    max_nodes: int = Field(default=50, ge=1, le=200)


class ContextExpansionResponse(BaseModel):
    """Respuesta de expansión de contexto."""

    center_node_id: str
    hops: int
    total_nodes: int
    nodes_by_distance: dict


class EntityTimelineRequest(BaseModel):
    """Request para timeline de entidad."""

    entity_name: str
    video_id: str


class EntityTimelineResponse(BaseModel):
    """Respuesta de timeline de entidad."""

    entity_name: str
    video_id: str
    occurrences: list[dict]
    total_occurrences: int


class RelatedEntitiesRequest(BaseModel):
    """Request para entidades relacionadas."""

    entity_id: str
    relation_types: list[RelationType] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ProcessVideoGraphRequest(BaseModel):
    """Request para procesar el grafo de un video."""

    video_id: str
    reprocess: bool = False
    include_semantic_relations: bool = True


class ProcessVideoGraphResponse(BaseModel):
    """Respuesta de procesamiento de grafo."""

    video_id: str
    status: str
    message: str
    stats: dict | None = None


# =============================================================================
# Hybrid Search Models
# =============================================================================


class HybridSearchRequest(BaseModel):
    """Request para búsqueda híbrida (vector + graph + fulltext)."""

    query: str
    node_types: list[NodeType] | None = None
    video_id: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    limit: int = Field(default=20, ge=1, le=100)
    expansion_hops: int = Field(default=2, ge=1, le=4)
    use_reranking: bool = True


class CrossVideoSearchRequest(BaseModel):
    """Request para búsqueda cross-video."""

    reference_node_id: str
    limit: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)


class CrossVideoSearchResponse(BaseModel):
    """Respuesta de búsqueda cross-video."""

    reference_node_id: str
    similar_nodes: list[dict]
    total_found: int


# =============================================================================
# Embedding Management Models
# =============================================================================


class GenerateEmbeddingsRequest(BaseModel):
    """Request para generar embeddings en bulk."""

    node_type: NodeType
    video_id: str | None = None
    batch_size: int = Field(default=50, ge=1, le=200)


class GenerateEmbeddingsResponse(BaseModel):
    """Respuesta de generación de embeddings."""

    node_type: str
    embeddings_generated: int
    video_id: str | None = None


class EmbeddingStatsResponse(BaseModel):
    """Estadísticas del servicio de embeddings."""

    total_requests: int
    cache_hits: int
    cache_hit_rate: float
    tokens_used: int


# =============================================================================
# Hierarchical Context Models
# =============================================================================


class ProcessHierarchyRequest(BaseModel):
    """Request para procesar jerarquía completa de un video."""

    video_path: str
    video_id: str
    title: str | None = None
    fps: float = 30.0
    duration: float | None = None
    resolution: tuple[int, int] = (1920, 1080)


class ProcessHierarchyResponse(BaseModel):
    """Respuesta de procesamiento jerárquico."""

    video_id: str
    status: str
    levels_processed: dict
    embeddings_generated: dict
    nodes_created: dict
    processing_time_seconds: float | None = None
    errors: list[str] = []


class DrillDownSearchRequest(BaseModel):
    """Request para búsqueda drill-down jerárquica."""

    query: str
    video_id: str | None = None
    start_level: str = Field(default="video", pattern="^(video|chapter|scene)$")
    target_level: str = Field(default="scene", pattern="^(video|chapter|scene|frame)$")
    top_k: int = Field(default=5, ge=1, le=20)
    include_context: bool = True


class HierarchyLevelResponse(BaseModel):
    """Representación de un nivel en la jerarquía."""

    level: str
    node_id: str
    node_type: str
    summary: str | None = None
    title: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    children_count: int = 0


class DrillDownSearchResponse(BaseModel):
    """Respuesta de búsqueda drill-down."""

    query: str
    results: list[dict]
    total_results: int
    levels_traversed: list[str]


class LoadChildrenRequest(BaseModel):
    """Request para carga lazy de hijos."""

    node_id: str
    node_type: NodeType
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class LoadChildrenResponse(BaseModel):
    """Respuesta de carga lazy."""

    parent_node_id: str
    children: list[HierarchyLevelResponse]
    total_children: int
    has_more: bool


class HierarchyStatsResponse(BaseModel):
    """Estadísticas de la jerarquía de un video."""

    video_id: str
    video_title: str | None = None
    duration_seconds: float | None = None
    hierarchy: dict
    embeddings: dict


class HierarchyPathResponse(BaseModel):
    """Ruta desde la raíz hasta un nodo."""

    node_id: str
    path: list[HierarchyLevelResponse]
    depth: int
