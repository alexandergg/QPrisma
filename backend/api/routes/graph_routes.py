"""
Knowledge Graph API Routes for QPrisma

Endpoints para gestionar el Knowledge Graph multimodal.
Incluye operaciones CRUD, búsqueda y graph expansion.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from models.graph_models import (
    EntityType,
    GraphSearchQuery,
    GraphSearchResponse,
    GraphSearchResult,
    GraphStats,
    NodeType,
    RelationType,
    VideoGraphSummary,
)
from services.embedding_service import get_embedding_service
from services.entity_extractor import get_entity_extractor
from services.graph_search_service import GraphSearchService, get_graph_search_service
from services.hierarchical_context_service import (
    HierarchicalContextService,
    get_hierarchical_context_service,
)
from services.knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


# =============================================================================
# Request/Response Models
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


# =============================================================================
# Lazy service initialization
# =============================================================================

_graph_service: KnowledgeGraphService | None = None
_search_service: GraphSearchService | None = None
_hierarchical_service: HierarchicalContextService | None = None


def get_graph_service() -> KnowledgeGraphService:
    """Obtiene el servicio del Knowledge Graph, inicializándolo si es necesario."""
    global _graph_service
    if _graph_service is None:
        _graph_service = get_knowledge_graph_service()
        if not _graph_service.is_connected:
            _graph_service.connect()
    return _graph_service


def get_search_service() -> GraphSearchService:
    """Obtiene el servicio de Graph Search, inicializándolo si es necesario."""
    global _search_service
    if _search_service is None:
        graph_svc = get_graph_service()
        _search_service = get_graph_search_service()
        _search_service.graph_service = graph_svc
    return _search_service


def get_hierarchy_service() -> HierarchicalContextService:
    """Obtiene el servicio de Hierarchical Context, inicializándolo si es necesario."""
    global _hierarchical_service
    if _hierarchical_service is None:
        graph_svc = get_graph_service()
        embedding_svc = get_embedding_service()
        _hierarchical_service = get_hierarchical_context_service(
            graph_service=graph_svc, embedding_service=embedding_svc
        )
    return _hierarchical_service


# =============================================================================
# Health & Status Endpoints
# =============================================================================


@router.get("/health", response_model=GraphHealthResponse)
async def graph_health_check():
    """
    Verifica el estado de conexión con Neo4j.
    """
    try:
        service = get_graph_service()
        connected = service.is_connected

        if not connected:
            connected = service.connect()

        return GraphHealthResponse(
            status="healthy" if connected else "unhealthy",
            connected=connected,
            uri=service.uri,
            message="Neo4j connection is active" if connected else "Failed to connect to Neo4j",
        )
    except Exception as e:
        logger.error(f"Graph health check failed: {e}")
        return GraphHealthResponse(
            status="error",
            connected=False,
            uri="unknown",
            message=str(e),
        )


@router.get("/stats", response_model=GraphStats)
async def get_graph_stats():
    """
    Obtiene estadísticas del Knowledge Graph.

    Incluye:
    - Total de nodos y relaciones
    - Conteos por tipo
    - Métricas del grafo
    """
    try:
        service = get_graph_service()
        stats = service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Search Endpoints
# =============================================================================


@router.post("/search/entities")
async def search_entities(request: EntitySearchRequest):
    """
    Búsqueda full-text de entidades en el Knowledge Graph.

    Soporta filtros por tipo de entidad y video.
    """
    try:
        service = get_graph_service()
        results = service.search_entities(
            query_text=request.query,
            entity_types=request.entity_types,
            video_id=request.video_id,
            limit=request.limit,
        )

        return {
            "query": request.query,
            "total_results": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Entity search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/frames")
async def search_frames(request: FrameSearchRequest):
    """
    Búsqueda full-text en descripciones de frames.

    Soporta filtros por video y rango temporal.
    """
    try:
        service = get_graph_service()

        time_range = None
        if request.time_start is not None and request.time_end is not None:
            time_range = (request.time_start, request.time_end)

        results = service.search_frames_by_description(
            query_text=request.query,
            video_id=request.video_id,
            time_range=time_range,
            limit=request.limit,
        )

        return {
            "query": request.query,
            "total_results": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Frame search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/advanced", response_model=GraphSearchResponse)
async def advanced_graph_search(query: GraphSearchQuery):
    """
    Búsqueda avanzada con expansión de grafo.

    Combina:
    - Búsqueda vectorial (si hay embeddings)
    - Búsqueda full-text
    - Expansión de contexto en el grafo
    """
    try:
        service = get_graph_service()
        start_time = __import__("time").time()

        # 1. Búsqueda base (full-text)
        base_results = []

        # Buscar en entidades
        if not query.node_types or NodeType.ENTITY in query.node_types:
            entity_results = service.search_entities(
                query_text=query.query,
                entity_types=query.entity_types,
                video_id=query.video_ids[0] if query.video_ids else None,
                limit=query.limit,
            )
            for r in entity_results:
                base_results.append(
                    {
                        "node_id": r["entity"].get("id"),
                        "node_type": NodeType.ENTITY,
                        "content": r["entity"],
                        "vector_score": r["score"],
                    }
                )

        # Buscar en frames
        if not query.node_types or NodeType.FRAME in query.node_types:
            frame_results = service.search_frames_by_description(
                query_text=query.query,
                video_id=query.video_ids[0] if query.video_ids else None,
                time_range=query.time_range,
                limit=query.limit,
            )
            for r in frame_results:
                base_results.append(
                    {
                        "node_id": r["frame"].get("id"),
                        "node_type": NodeType.FRAME,
                        "content": r["frame"],
                        "vector_score": r["score"],
                    }
                )

        vector_search_time = (time.time() - start_time) * 1000

        # 2. Expansión de grafo (si está habilitada)
        graph_expansion_time = 0
        if query.use_graph_expansion and base_results:
            expansion_start = time.time()

            for result in base_results[:10]:  # Limitar expansión a top 10
                try:
                    expansion = service.expand_context(
                        node_id=result["node_id"],
                        hops=query.expansion_hops,
                        max_nodes=20,
                    )
                    result["related_nodes"] = expansion.get("nodes_by_distance", {})
                except Exception:
                    result["related_nodes"] = {}

            graph_expansion_time = (time.time() - expansion_start) * 1000

        # 3. Construir respuesta
        search_results = []
        for r in base_results[: query.limit]:
            search_results.append(
                GraphSearchResult(
                    node_id=r["node_id"],
                    node_type=r["node_type"],
                    vector_score=r.get("vector_score", 0),
                    graph_score=0,  # TODO: Calcular basado en expansión
                    combined_score=r.get("vector_score", 0),
                    content=r["content"],
                    related_nodes=r.get("related_nodes", []),
                )
            )

        total_time = (time.time() - start_time) * 1000

        return GraphSearchResponse(
            query=query.query,
            total_results=len(search_results),
            results=search_results,
            search_time_ms=total_time,
            vector_search_time_ms=vector_search_time,
            graph_expansion_time_ms=graph_expansion_time,
        )

    except Exception as e:
        logger.error(f"Advanced search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Hybrid Search Endpoints (Graph-Enhanced Retrieval)
# =============================================================================


@router.post("/search/hybrid", response_model=GraphSearchResponse)
async def hybrid_search(request: HybridSearchRequest):
    """
    Búsqueda híbrida combinando vector, full-text y graph.

    Combina múltiples señales de relevancia:
    - **Vector similarity**: Similitud semántica via embeddings
    - **Full-text match**: Coincidencia de términos
    - **Graph proximity**: Cercanía en el grafo (hops)
    - **Temporal relevance**: Cercanía temporal en el video

    Incluye re-ranking con contexto expandido para mejores resultados.
    """
    try:
        search_service = get_search_service()

        time_range = None
        if request.time_start is not None and request.time_end is not None:
            time_range = (request.time_start, request.time_end)

        response = search_service.hybrid_search(
            query_text=request.query,
            node_types=request.node_types,
            video_id=request.video_id,
            time_range=time_range,
            limit=request.limit,
            expansion_hops=request.expansion_hops,
            use_reranking=request.use_reranking,
        )

        return response

    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/cross-video", response_model=CrossVideoSearchResponse)
async def cross_video_search(request: CrossVideoSearchRequest):
    """
    Encuentra nodos similares en otros videos.

    Útil para:
    - Encontrar la misma persona/objeto en diferentes videos
    - Descubrir contenido relacionado entre videos
    - Crear relaciones SAME_ENTITY cross-video
    """
    try:
        search_service = get_search_service()

        similar_nodes = search_service.find_similar_across_videos(
            reference_node_id=request.reference_node_id,
            limit=request.limit,
            min_similarity=request.min_similarity,
        )

        return CrossVideoSearchResponse(
            reference_node_id=request.reference_node_id,
            similar_nodes=[
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type.value,
                    "video_id": n.video_id,
                    "similarity": n.vector_score,
                    "content": n.content,
                }
                for n in similar_nodes
            ],
            total_found=len(similar_nodes),
        )

    except Exception as e:
        logger.error(f"Cross-video search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Embedding Management Endpoints
# =============================================================================


@router.post("/embeddings/generate", response_model=GenerateEmbeddingsResponse)
async def generate_embeddings(
    request: GenerateEmbeddingsRequest, background_tasks: BackgroundTasks
):
    """
    Genera embeddings en bulk para nodos existentes.

    Procesa nodos que no tienen embedding y genera usando text-embedding-3-large.
    Puede filtrar por tipo de nodo y video.

    Nota: Para grandes cantidades, considerar ejecutar en background.
    """
    try:
        search_service = get_search_service()

        # Determinar campo de texto según tipo de nodo
        text_field = "description"
        if request.node_type == NodeType.ENTITY:
            text_field = "name"
        elif request.node_type == NodeType.AUDIO_SEGMENT:
            text_field = "text"

        count = search_service.bulk_generate_embeddings(
            node_type=request.node_type,
            text_field=text_field,
            batch_size=request.batch_size,
            video_id=request.video_id,
        )

        return GenerateEmbeddingsResponse(
            node_type=request.node_type.value,
            embeddings_generated=count,
            video_id=request.video_id,
        )

    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embeddings/stats", response_model=EmbeddingStatsResponse)
async def get_embedding_stats():
    """
    Obtiene estadísticas del servicio de embeddings.

    Incluye:
    - Total de requests
    - Cache hits
    - Tokens usados
    """
    try:
        embedding_service = get_embedding_service()
        stats = embedding_service.get_stats()

        return EmbeddingStatsResponse(
            total_requests=stats["total_requests"],
            cache_hits=stats["cache_hits"],
            cache_hit_rate=stats["cache_hit_rate"],
            tokens_used=stats["tokens_used"],
        )

    except Exception as e:
        logger.error(f"Failed to get embedding stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Context & Expansion Endpoints
# =============================================================================


@router.post("/expand", response_model=ContextExpansionResponse)
async def expand_context(request: ContextExpansionRequest):
    """
    Expande el contexto de un nodo para RAG.

    Retorna nodos relacionados hasta N hops de distancia.
    Útil para enriquecer el contexto en consultas RAG.
    """
    try:
        service = get_graph_service()
        result = service.expand_context(
            node_id=request.node_id,
            hops=request.hops,
            relation_types=request.relation_types,
            max_nodes=request.max_nodes,
        )

        return ContextExpansionResponse(
            center_node_id=result["center_node_id"],
            hops=result["hops"],
            total_nodes=result["total_nodes"],
            nodes_by_distance=result["nodes_by_distance"],
        )
    except Exception as e:
        logger.error(f"Context expansion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeline", response_model=EntityTimelineResponse)
async def get_entity_timeline(request: EntityTimelineRequest):
    """
    Obtiene la línea temporal de apariciones de una entidad en un video.

    Útil para entender cuándo y dónde aparece una entidad.
    """
    try:
        service = get_graph_service()
        occurrences = service.get_entity_timeline(
            entity_name=request.entity_name,
            video_id=request.video_id,
        )

        return EntityTimelineResponse(
            entity_name=request.entity_name,
            video_id=request.video_id,
            occurrences=occurrences,
            total_occurrences=len(occurrences),
        )
    except Exception as e:
        logger.error(f"Failed to get entity timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/related")
async def get_related_entities(request: RelatedEntitiesRequest):
    """
    Obtiene entidades relacionadas a una entidad dada.

    Soporta filtros por tipo de relación.
    """
    try:
        service = get_graph_service()
        results = service.get_related_entities(
            entity_id=request.entity_id,
            relation_types=request.relation_types,
            limit=request.limit,
        )

        return {
            "entity_id": request.entity_id,
            "total_related": len(results),
            "related_entities": results,
        }
    except Exception as e:
        logger.error(f"Failed to get related entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Video Graph Operations
# =============================================================================


@router.get("/video/{video_id}")
async def get_video_graph(video_id: str):
    """
    Obtiene el subgrafo completo de un video.

    Incluye scenes, frames, entities y relaciones.
    """
    try:
        service = get_graph_service()

        # Obtener nodo de video
        video = service.get_video_node(video_id)
        if not video:
            raise HTTPException(status_code=404, detail=f"Video {video_id} not found in graph")

        # Obtener scenes
        scenes = service.get_video_scenes(video_id)

        # Estadísticas básicas
        stats = service.get_stats()

        return {
            "video": video,
            "scenes": scenes,
            "total_scenes": len(scenes),
            "graph_stats": stats.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get video graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/video/{video_id}")
async def delete_video_graph(video_id: str):
    """
    Elimina todo el subgrafo asociado a un video.

    Incluye scenes, frames, entities y relaciones.
    """
    try:
        service = get_graph_service()
        deleted_count = service.delete_video_graph(video_id)

        return {
            "status": "success",
            "video_id": video_id,
            "deleted_nodes": deleted_count,
        }
    except Exception as e:
        logger.error(f"Failed to delete video graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/video/{video_id}/summary", response_model=VideoGraphSummary)
async def get_video_graph_summary(video_id: str):
    """
    Obtiene un resumen del grafo de un video.

    Incluye entidades más frecuentes, temas principales, etc.
    """
    # TODO: Implementar query de resumen
    raise HTTPException(status_code=501, detail="Not implemented yet")


# =============================================================================
# Entity Extraction Endpoints
# =============================================================================


@router.post("/extract/frame")
async def extract_entities_from_frame(
    image_url: str,
    timestamp: float = 0.0,
    context: str = "",
):
    """
    Extrae entidades de un frame individual usando GPT-4o.

    Útil para testing o procesamiento manual.
    """
    try:
        extractor = get_entity_extractor()
        result = extractor.extract_from_image(
            image_source=image_url,
            timestamp=timestamp,
            context=context,
            is_url=True,
        )

        return {
            "frame_id": result.frame_id,
            "timestamp": result.timestamp,
            "description": result.description,
            "entities": [e.model_dump() for e in result.entities],
            "relations": result.relations,
            "topics": result.topics,
            "actions": result.actions,
            "analysis_time_ms": result.analysis_time_ms,
        }
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/description")
async def extract_entities_from_description(
    description: str,
    timestamp: float = 0.0,
    context: str = "",
):
    """
    Extrae entidades de una descripción textual de frame.

    Útil para re-procesar frames que ya tienen descripción.
    """
    try:
        extractor = get_entity_extractor()
        result = extractor.extract_from_description(
            description=description,
            timestamp=timestamp,
            context=context,
        )

        return {
            "frame_id": result.frame_id,
            "timestamp": result.timestamp,
            "entities": [e.model_dump() for e in result.entities],
            "relations": result.relations,
            "topics": result.topics,
            "actions": result.actions,
            "analysis_time_ms": result.analysis_time_ms,
        }
    except Exception as e:
        logger.error(f"Entity extraction from description failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Hierarchical Context Endpoints (Phase 2.3)
# =============================================================================


@router.post("/hierarchy/process", response_model=ProcessHierarchyResponse)
async def process_video_hierarchy(
    request: ProcessHierarchyRequest, background_tasks: BackgroundTasks
):
    """
    Procesa un video para crear su jerarquía completa.

    Pipeline:
    1. Detecta escenas usando FFmpeg
    2. Genera capítulos agrupando escenas
    3. Crea resúmenes jerárquicos (scene → chapter → video)
    4. Genera embeddings en cada nivel
    5. Almacena en Neo4j Knowledge Graph

    Ideal para videos largos (100+ minutos) que necesitan
    navegación jerárquica y búsqueda drill-down.
    """
    try:
        hierarchy_service = get_hierarchy_service()

        video_metadata = {
            "media_id": request.video_id,
            "video_id": request.video_id,
            "title": request.title or f"Video {request.video_id}",
            "fps": request.fps,
            "duration": request.duration or 0,
            "resolution": request.resolution,
            "file_size_bytes": 0,
            "format": "mp4",
        }

        result = await hierarchy_service.process_video_hierarchy(
            video_path=request.video_path, video_metadata=video_metadata
        )

        return ProcessHierarchyResponse(
            video_id=result["video_id"],
            status=result["status"],
            levels_processed=result.get("levels_processed", {}),
            embeddings_generated=result.get("embeddings_generated", {}),
            nodes_created=result.get("nodes_created", {}),
            processing_time_seconds=result.get("processing_time_seconds"),
            errors=result.get("errors", []),
        )

    except Exception as e:
        logger.error(f"Hierarchy processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hierarchy/search/drill-down", response_model=DrillDownSearchResponse)
async def drill_down_search(request: DrillDownSearchRequest):
    """
    Búsqueda jerárquica drill-down.

    Comienza en un nivel alto (video/chapter) y desciende al nivel
    objetivo basándose en relevancia semántica.

    Ideal para:
    - Navegar videos largos eficientemente
    - Encontrar escenas específicas partiendo del contexto general
    - Exploración progresiva de contenido

    Ejemplo de uso:
    1. Buscar "presentación de producto" a nivel video
    2. Drill-down a chapters relevantes
    3. Encontrar escenas específicas dentro de esos chapters
    """
    try:
        hierarchy_service = get_hierarchy_service()

        results = await hierarchy_service.drill_down_search(
            query_text=request.query,
            video_id=request.video_id,
            start_level=request.start_level,
            target_level=request.target_level,
            top_k=request.top_k,
            include_context=request.include_context,
        )

        # Convert to response format
        formatted_results = []
        levels_traversed = set()

        for result in results:
            levels_traversed.update([level.level for level in result.path_from_root])
            formatted_results.append(
                {
                    "current_level": {
                        "level": result.current_level.level,
                        "node_id": result.current_level.node_id,
                        "node_type": result.current_level.node_type.value,
                        "summary": result.current_level.summary,
                        "title": result.current_level.title,
                        "start_time": result.current_level.start_time,
                        "end_time": result.current_level.end_time,
                    },
                    "path": [
                        {
                            "level": level.level,
                            "node_id": level.node_id,
                            "title": level.title,
                        }
                        for level in result.path_from_root
                    ],
                    "has_more_levels": result.has_more_levels,
                }
            )

        return DrillDownSearchResponse(
            query=request.query,
            results=formatted_results,
            total_results=len(formatted_results),
            levels_traversed=list(levels_traversed),
        )

    except Exception as e:
        logger.error(f"Drill-down search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hierarchy/children", response_model=LoadChildrenResponse)
async def load_children(request: LoadChildrenRequest):
    """
    Carga lazy de nodos hijos.

    Permite cargar hijos de un nodo bajo demanda, sin necesidad
    de cargar toda la jerarquía de una vez.

    Soporta paginación para niveles con muchos hijos.
    """
    try:
        hierarchy_service = get_hierarchy_service()

        children = await hierarchy_service.load_children(
            node_id=request.node_id,
            node_type=request.node_type,
            limit=request.limit + 1,  # +1 to check if there's more
            offset=request.offset,
        )

        has_more = len(children) > request.limit
        if has_more:
            children = children[: request.limit]

        return LoadChildrenResponse(
            parent_node_id=request.node_id,
            children=[
                HierarchyLevelResponse(
                    level=child.level,
                    node_id=child.node_id,
                    node_type=child.node_type.value,
                    summary=child.summary,
                    title=child.title,
                    start_time=child.start_time,
                    end_time=child.end_time,
                    children_count=child.children_count,
                )
                for child in children
            ],
            total_children=len(children),
            has_more=has_more,
        )

    except Exception as e:
        logger.error(f"Load children failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hierarchy/stats/{video_id}", response_model=HierarchyStatsResponse)
async def get_hierarchy_stats(video_id: str):
    """
    Obtiene estadísticas de la jerarquía de un video.

    Incluye:
    - Conteo de chapters, scenes, frames
    - Estado de embeddings por nivel
    - Duración y título del video
    """
    try:
        hierarchy_service = get_hierarchy_service()
        stats = await hierarchy_service.get_hierarchy_stats(video_id)

        if "error" in stats:
            raise HTTPException(status_code=404, detail=stats["error"])

        return HierarchyStatsResponse(
            video_id=stats["video_id"],
            video_title=stats.get("video_title"),
            duration_seconds=stats.get("duration_seconds"),
            hierarchy=stats.get("hierarchy", {}),
            embeddings=stats.get("embeddings", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get hierarchy stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hierarchy/path/{node_id}", response_model=HierarchyPathResponse)
async def get_hierarchy_path(node_id: str, node_type: NodeType = Query(NodeType.SCENE)):
    """
    Obtiene la ruta completa desde la raíz (video) hasta un nodo.

    Útil para:
    - Navegación breadcrumb
    - Entender el contexto de un resultado de búsqueda
    - Construir URLs de navegación
    """
    try:
        hierarchy_service = get_hierarchy_service()
        path = await hierarchy_service.get_hierarchy_path(node_id, node_type)

        return HierarchyPathResponse(
            node_id=node_id,
            path=[
                HierarchyLevelResponse(
                    level=level.level,
                    node_id=level.node_id,
                    node_type=level.node_type.value,
                    summary=level.summary,
                    title=level.title,
                    start_time=level.start_time,
                    end_time=level.end_time,
                )
                for level in path
            ],
            depth=len(path),
        )

    except Exception as e:
        logger.error(f"Get hierarchy path failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.delete("/clear", include_in_schema=False)
async def clear_all_graph_data(confirm: bool = Query(False)):
    """
    Elimina TODOS los datos del Knowledge Graph.

    PELIGROSO - Solo para desarrollo/testing.
    Requiere confirmación explícita.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must confirm deletion with ?confirm=true",
        )

    try:
        service = get_graph_service()
        service.clear_all()
        return {"status": "success", "message": "All graph data has been deleted"}
    except Exception as e:
        logger.error(f"Failed to clear graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Importar time al inicio del módulo
import time
