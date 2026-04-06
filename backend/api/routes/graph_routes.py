"""
Knowledge Graph API Routes for QPrisma

Endpoints for managing the multimodal Knowledge Graph.
Includes CRUD operations, search, and graph expansion.

Route handlers are intentionally thin: validate input → call service → return
response.  Business logic lives in :mod:`services.graph_route_service`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import (
    get_current_user,
    get_graph_node_media_or_404,
    get_graph_route_service,
    get_graph_search_service,
    get_hierarchical_context_service,
    get_knowledge_graph_service,
    get_media_or_404,
)
from core.exceptions import internal_error, not_found_error
from models.graph_models import (
    GraphSearchQuery,
    GraphSearchResponse,
    GraphStats,
    NodeType,
    VideoGraphSummary,
)
from models.graph_route_schemas import (
    ContextExpansionRequest,
    ContextExpansionResponse,
    CrossVideoSearchRequest,
    CrossVideoSearchResponse,
    DrillDownSearchRequest,
    DrillDownSearchResponse,
    EmbeddingStatsResponse,
    EntitySearchRequest,
    EntityTimelineRequest,
    EntityTimelineResponse,
    ExpandSubgraphRequest,
    FrameSearchRequest,
    GenerateEmbeddingsRequest,
    GenerateEmbeddingsResponse,
    GraphHealthResponse,
    GraphVisualizationResponse,
    HierarchyLevelResponse,
    HierarchyPathResponse,
    HierarchyStatsResponse,
    HybridSearchRequest,
    LoadChildrenRequest,
    LoadChildrenResponse,
    NvlNode,
    NvlRelationship,
    ProcessHierarchyRequest,
    ProcessHierarchyResponse,
    RelatedEntitiesRequest,
)
from models.user import User
from services.embedding_service import get_embedding_service
from services.entity_extractor import get_entity_extractor
from services.graph_route_service import GraphRouteService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


# =============================================================================
# Health & Status Endpoints
# =============================================================================


@router.get("/health", response_model=GraphHealthResponse)
async def graph_health_check(current_user: User = Depends(get_current_user)):
    """
    Verifies the connection status with Neo4j.
    """
    try:
        service = get_knowledge_graph_service()
        svc: GraphRouteService = get_graph_route_service()
        result = svc.check_graph_health(service)
        return GraphHealthResponse(
            status=result.status,
            connected=result.connected,
            uri=result.uri,
            message=result.message,
        )
    except Exception as e:
        logger.error(f"Graph health check failed: {e}", exc_info=True)
        return GraphHealthResponse(
            status="error",
            connected=False,
            uri="unknown",
            message="Unexpected error during health check",
        )


@router.get("/stats", response_model=GraphStats)
async def get_graph_stats(current_user: User = Depends(get_current_user)):
    """
    Gets Knowledge Graph statistics.

    Includes:
    - Total nodes and relationships
    - Counts by type
    - Graph metrics
    """
    try:
        service = get_knowledge_graph_service()
        stats = service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Search Endpoints
# =============================================================================


@router.post("/search/entities")
async def search_entities(
    request: EntitySearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Full-text search of entities in the Knowledge Graph.

    Supports filters by entity type and video.
    """
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)

        service = get_knowledge_graph_service()
        results = service.search_entities(
            query_text=request.query,
            entity_types=request.entity_types,
            video_id=request.video_id,
            user_id=current_user.id,
            limit=request.limit,
        )

        return {
            "query": request.query,
            "total_results": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Entity search failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/search/frames")
async def search_frames(
    request: FrameSearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Full-text search in frame descriptions.

    Supports filters by video and temporal range.
    """
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)

        service = get_knowledge_graph_service()
        time_range = GraphRouteService.build_time_range(request.time_start, request.time_end)

        results = service.search_frames_by_description(
            query_text=request.query,
            video_id=request.video_id,
            user_id=current_user.id,
            time_range=time_range,
            limit=request.limit,
        )

        return {
            "query": request.query,
            "total_results": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Frame search failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/search/advanced", response_model=GraphSearchResponse)
async def advanced_graph_search(
    query: GraphSearchQuery, current_user: User = Depends(get_current_user)
):
    """
    Advanced search with graph expansion.

    Combines:
    - Vector search (if embeddings available)
    - Full-text search
    - Context expansion in the graph
    """
    try:
        if query.video_ids:
            for video_id in query.video_ids:
                get_media_or_404(video_id, current_user)

        svc: GraphRouteService = get_graph_route_service()
        result = svc.advanced_search(query, user_id=current_user.id)

        if result.error:
            logger.error(f"Advanced search error: {result.error}")
            raise internal_error()

        return result.response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Advanced search failed: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Hybrid Search Endpoints (Graph-Enhanced Retrieval)
# =============================================================================


@router.post("/search/hybrid", response_model=GraphSearchResponse)
async def hybrid_search(
    request: HybridSearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Hybrid search combining vector, full-text, and graph.

    Combines multiple relevance signals:
    - **Vector similarity**: Semantic similarity via embeddings
    - **Full-text match**: Term matching
    - **Graph proximity**: Closeness in the graph (hops)
    - **Temporal relevance**: Temporal proximity in the video

    Includes re-ranking with expanded context for better results.
    """
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)

        search_service = get_graph_search_service()
        time_range = GraphRouteService.build_time_range(request.time_start, request.time_end)

        response = await search_service.hybrid_search(
            query_text=request.query,
            node_types=request.node_types,
            video_id=request.video_id,
            user_id=current_user.id,
            time_range=time_range,
            limit=request.limit,
            expansion_hops=request.expansion_hops,
            use_reranking=request.use_reranking,
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/search/cross-video", response_model=CrossVideoSearchResponse)
async def cross_video_search(
    request: CrossVideoSearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Finds similar nodes in other videos.

    Useful for:
    - Finding the same person/object in different videos
    - Discovering related content between videos
    - Creating SAME_ENTITY relationships cross-video
    """
    try:
        get_graph_node_media_or_404(request.reference_node_id, current_user)
        search_service = get_graph_search_service()
        scoped_user_id = None if current_user.is_superuser else current_user.id

        similar_nodes = search_service.find_similar_across_videos(
            reference_node_id=request.reference_node_id,
            limit=request.limit,
            min_similarity=request.min_similarity,
            user_id=scoped_user_id,
        )

        return CrossVideoSearchResponse(
            reference_node_id=request.reference_node_id,
            similar_nodes=GraphRouteService.build_cross_video_results(similar_nodes),
            total_found=len(similar_nodes),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cross-video search failed: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Embedding Management Endpoints
# =============================================================================


@router.post("/embeddings/generate", response_model=GenerateEmbeddingsResponse)
async def generate_embeddings(
    request: GenerateEmbeddingsRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generates embeddings in bulk for existing nodes.

    Processes nodes that don't have embeddings and generates using text-embedding-3-large.
    Can filter by node type and video.

    Note: For large quantities, consider running in background.
    """
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)
        elif not current_user.is_superuser:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to generate embeddings across all videos",
            )

        search_service = get_graph_search_service()
        text_field = GraphRouteService.determine_text_field(request.node_type)

        count = await search_service.bulk_generate_embeddings(
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/embeddings/stats", response_model=EmbeddingStatsResponse)
async def get_embedding_stats(current_user: User = Depends(get_current_user)):
    """
    Gets embedding service statistics.

    Includes:
    - Total requests
    - Cache hits
    - Tokens used
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
        logger.error(f"Failed to get embedding stats: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Context & Expansion Endpoints
# =============================================================================


@router.post("/expand", response_model=ContextExpansionResponse)
async def expand_context(
    request: ContextExpansionRequest, current_user: User = Depends(get_current_user)
):
    """
    Expands the context of a node for RAG.

    Returns related nodes up to N hops distance.
    Useful for enriching context in RAG queries.
    """
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        service = get_knowledge_graph_service()
        result = service.expand_context(
            node_id=request.node_id,
            hops=request.hops,
            relation_types=request.relation_types,
            max_nodes=request.max_nodes,
            user_id=current_user.id,
        )

        return ContextExpansionResponse(
            center_node_id=result["center_node_id"],
            hops=result["hops"],
            total_nodes=result["total_nodes"],
            nodes_by_distance=result["nodes_by_distance"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Context expansion failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/timeline", response_model=EntityTimelineResponse)
async def get_entity_timeline(
    request: EntityTimelineRequest, current_user: User = Depends(get_current_user)
):
    """
    Gets the timeline of entity appearances in a video.

    Useful for understanding when and where an entity appears.
    """
    try:
        get_media_or_404(request.video_id, current_user)
        service = get_knowledge_graph_service()
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get entity timeline: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/related")
async def get_related_entities(
    request: RelatedEntitiesRequest, current_user: User = Depends(get_current_user)
):
    """
    Gets entities related to a given entity.

    Supports filters by relationship type.
    """
    try:
        get_graph_node_media_or_404(request.entity_id, current_user)
        service = get_knowledge_graph_service()
        results = service.get_related_entities(
            entity_id=request.entity_id,
            relation_types=request.relation_types,
            limit=request.limit,
            user_id=current_user.id,
        )

        return {
            "entity_id": request.entity_id,
            "total_related": len(results),
            "related_entities": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get related entities: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Video Graph Operations
# =============================================================================


@router.get("/video/{video_id}")
async def get_video_graph(video_id: str, current_user: User = Depends(get_current_user)):
    """
    Gets the complete subgraph of a video.

    Includes scenes, frames, entities, and relationships.
    """
    try:
        get_media_or_404(video_id, current_user)
        svc: GraphRouteService = get_graph_route_service()
        data = svc.get_video_graph_data(video_id)

        if data.error:
            raise not_found_error("Video", video_id)

        return {
            "video": data.video,
            "scenes": data.scenes,
            "total_scenes": data.total_scenes,
            "graph_stats": data.graph_stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get video graph: {e}", exc_info=True)
        raise internal_error() from e


@router.delete("/video/{video_id}")
async def delete_video_graph(video_id: str, current_user: User = Depends(get_current_user)):
    """
    Deletes all subgraph associated with a video.

    Includes scenes, frames, entities, and relationships.
    """
    try:
        get_media_or_404(video_id, current_user)
        service = get_knowledge_graph_service()
        deleted_count = service.delete_video_graph(video_id)

        return {
            "status": "success",
            "video_id": video_id,
            "deleted_nodes": deleted_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete video graph: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/video/{video_id}/summary", response_model=VideoGraphSummary)
async def get_video_graph_summary(video_id: str, current_user: User = Depends(get_current_user)):
    """
    Gets a summary of a video's graph.

    Includes most frequent entities, main topics, etc.
    """
    get_media_or_404(video_id, current_user)
    # TODO: Implement summary query
    raise HTTPException(status_code=501, detail="Not implemented yet")


# =============================================================================
# Entity Extraction Endpoints
# =============================================================================


@router.post("/extract/frame")
async def extract_entities_from_frame(
    image_url: str,
    timestamp: float = 0.0,
    context: str = "",
    current_user: User = Depends(get_current_user),
):
    """
    Extracts entities from an individual frame using GPT-4o.

    Useful for testing or manual processing.
    """
    try:
        extractor = get_entity_extractor()
        result = extractor.extract_from_image(
            image_source=image_url,
            timestamp=timestamp,
            context=context,
            is_url=True,
        )

        return GraphRouteService.format_frame_extraction_result(result)
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/extract/description")
async def extract_entities_from_description(
    description: str,
    timestamp: float = 0.0,
    context: str = "",
    current_user: User = Depends(get_current_user),
):
    """
    Extracts entities from a textual frame description.

    Useful for re-processing frames that already have a description.
    """
    try:
        extractor = get_entity_extractor()
        result = extractor.extract_from_description(
            description=description,
            timestamp=timestamp,
            context=context,
        )

        return GraphRouteService.format_description_extraction_result(result)
    except Exception as e:
        logger.error(f"Entity extraction from description failed: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Hierarchical Context Endpoints (Phase 2.3)
# =============================================================================


@router.post("/hierarchy/process", response_model=ProcessHierarchyResponse)
async def process_video_hierarchy(
    request: ProcessHierarchyRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Processes a video to create its complete hierarchy.

    Pipeline:
    1. Detects scenes using FFmpeg
    2. Generates chapters by grouping scenes
    3. Creates hierarchical summaries (scene → chapter → video)
    4. Generates embeddings at each level
    5. Stores in Neo4j Knowledge Graph

    Ideal for long videos (100+ minutes) that need
    hierarchical navigation and drill-down search.
    """
    try:
        get_media_or_404(request.video_id, current_user)
        hierarchy_service = get_hierarchical_context_service()
        svc: GraphRouteService = get_graph_route_service()

        video_metadata = svc.build_hierarchy_metadata(
            video_id=request.video_id,
            title=request.title,
            fps=request.fps,
            duration=request.duration,
            resolution=request.resolution,
            user_id=current_user.id,
        )

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Hierarchy processing failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/hierarchy/search/drill-down", response_model=DrillDownSearchResponse)
async def drill_down_search(
    request: DrillDownSearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Hierarchical drill-down search.

    Starts at a high level (video/chapter) and descends to the target
    level based on semantic relevance.

    Ideal for:
    - Efficiently navigating long videos
    - Finding specific scenes starting from general context
    - Progressive content exploration

    Usage example:
    1. Search "product presentation" at video level
    2. Drill-down to relevant chapters
    3. Find specific scenes within those chapters
    """
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)

        hierarchy_service = get_hierarchical_context_service()

        results = await hierarchy_service.drill_down_search(
            query_text=request.query,
            video_id=request.video_id,
            start_level=request.start_level,
            target_level=request.target_level,
            top_k=request.top_k,
            include_context=request.include_context,
        )

        formatted = GraphRouteService.format_drill_down_results(results)

        return DrillDownSearchResponse(
            query=request.query,
            results=formatted.results,
            total_results=formatted.total_results,
            levels_traversed=formatted.levels_traversed,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Drill-down search failed: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/hierarchy/children", response_model=LoadChildrenResponse)
async def load_children(
    request: LoadChildrenRequest, current_user: User = Depends(get_current_user)
):
    """
    Lazy loading of child nodes.

    Allows loading children of a node on demand, without needing
    to load the entire hierarchy at once.

    Supports pagination for levels with many children.
    """
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        hierarchy_service = get_hierarchical_context_service()

        children = await hierarchy_service.load_children(
            node_id=request.node_id,
            node_type=request.node_type,
            limit=request.limit + 1,  # +1 to check if there's more
            offset=request.offset,
        )

        paginated = GraphRouteService.paginate_children(children, request.limit)

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
                for child in paginated.children
            ],
            total_children=paginated.total_children,
            has_more=paginated.has_more,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Load children failed: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/hierarchy/stats/{video_id}", response_model=HierarchyStatsResponse)
async def get_hierarchy_stats(video_id: str, current_user: User = Depends(get_current_user)):
    """
    Gets hierarchy statistics for a video.

    Includes:
    - Chapter, scene, and frame counts
    - Embedding status per level
    - Video duration and title
    """
    try:
        get_media_or_404(video_id, current_user)
        hierarchy_service = get_hierarchical_context_service()
        stats = await hierarchy_service.get_hierarchy_stats(video_id)

        if "error" in stats:
            raise not_found_error("Video hierarchy", video_id)

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
        logger.error(f"Get hierarchy stats failed: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/hierarchy/path/{node_id}", response_model=HierarchyPathResponse)
async def get_hierarchy_path(
    node_id: str,
    node_type: NodeType = Query(NodeType.SCENE),
    current_user: User = Depends(get_current_user),
):
    """
    Gets the full path from the root (video) to a node.

    Useful for:
    - Breadcrumb navigation
    - Understanding the context of a search result
    - Building navigation URLs
    """
    try:
        get_graph_node_media_or_404(node_id, current_user)
        hierarchy_service = get_hierarchical_context_service()
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get hierarchy path failed: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.delete("/clear", include_in_schema=False)
async def clear_all_graph_data(
    confirm: bool = Query(False), current_user: User = Depends(get_current_user)
):
    """
    Deletes ALL data from the Knowledge Graph.

    DANGEROUS - For development/testing only.
    Requires explicit confirmation.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must confirm deletion with ?confirm=true",
        )

    try:
        service = get_knowledge_graph_service()
        service.clear_all()
        return {"status": "success", "message": "All graph data has been deleted"}
    except Exception as e:
        logger.error(f"Failed to clear graph: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Graph Visualization Endpoints (NVL)
# =============================================================================

# Visual mapping: NodeType -> (color, size)
_NODE_VISUAL_MAP: dict[str, tuple[str, int]] = {
    "Video": ("#4F46E5", 40),  # indigo-600
    "Chapter": ("#7C3AED", 30),  # violet-600
    "Scene": ("#6366F1", 25),  # indigo-500
    "Frame": ("#06B6D4", 15),  # cyan-500
    "Entity": ("#8B5CF6", 18),  # violet-500 (default, overridden per entity type)
    "AudioSegment": ("#10B981", 15),  # emerald-500
    "Topic": ("#F59E0B", 20),  # amber-500
}

_ENTITY_COLOR_MAP: dict[str, str] = {
    "person": "#EC4899",
    "object": "#8B5CF6",
    "location": "#14B8A6",
    "action": "#F97316",
    "concept": "#6366F1",
    "text": "#64748B",
    "brand": "#EF4444",
    "event": "#A855F7",
}


def _raw_to_nvl_node(raw: dict) -> NvlNode:
    """Convert a raw Neo4j node dict to NVL format with visual styling."""
    labels = raw.get("labels", [])
    props = raw.get("properties", {})
    node_id = raw.get("id") or props.get("id", "")

    # Determine primary label (NodeType)
    node_type = "Entity"  # default
    for label in labels:
        if label in _NODE_VISUAL_MAP:
            node_type = label
            break

    color, size = _NODE_VISUAL_MAP.get(node_type, ("#6366F1", 20))

    # Entity subtype coloring
    entity_type = props.get("entity_type")
    if node_type == "Entity" and entity_type:
        color = _ENTITY_COLOR_MAP.get(entity_type, color)

    # Build caption from best available property
    caption = (
        props.get("title")
        or props.get("name")
        or props.get("normalized_name")
        or props.get("description", "")[:40]
        or f"{node_type}"
    )
    if node_type == "Frame":
        ts = props.get("timestamp")
        caption = f"{ts:.1f}s" if ts is not None else "Frame"
    elif node_type == "AudioSegment":
        start = props.get("start_time", 0)
        end = props.get("end_time", 0)
        caption = f"{start:.0f}–{end:.0f}s"

    # Strip embedding arrays from properties to keep payload small
    clean_props = {k: v for k, v in props.items() if k != "embedding"}

    return NvlNode(
        id=str(node_id),
        caption=str(caption),
        color=color,
        size=size,
        node_type=node_type,
        entity_type=entity_type,
        properties=clean_props,
    )


def _raw_to_nvl_rel(raw: dict) -> NvlRelationship:
    """Convert a raw Neo4j relationship dict to NVL format."""
    rel_type = raw.get("type", "RELATES_TO")
    return NvlRelationship(
        id=str(raw.get("id", "")),
        **{"from": str(raw.get("start", ""))},
        to=str(raw.get("end", "")),
        caption=rel_type.replace("_", " ").title(),
        type=rel_type,
        properties=raw.get("properties", {}),
    )


@router.get("/video/{video_id}/visualization", response_model=GraphVisualizationResponse)
async def get_video_visualization(
    video_id: str,
    depth: int = Query(default=2, ge=1, le=4),
    include_entities: bool = Query(default=True),
    max_nodes: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the video Knowledge Graph in NVL-compatible format.

    Returns nodes and relationships styled for @neo4j-nvl/react:
    - Nodes have id, caption, color, size, node_type, properties
    - Relationships have id, from, to, caption, type, properties
    """
    try:
        get_media_or_404(video_id, current_user)
        service = get_knowledge_graph_service()
        subgraph = service.get_video_subgraph(
            video_id=video_id,
            depth=depth,
            include_entities=include_entities,
            max_nodes=max_nodes,
        )

        raw_nodes = subgraph.get("nodes", [])
        raw_rels = subgraph.get("relationships", [])

        if not raw_nodes:
            raise not_found_error("Video", video_id)

        nvl_nodes = [_raw_to_nvl_node(n) for n in raw_nodes]
        nvl_rels = [_raw_to_nvl_rel(r) for r in raw_rels]

        return GraphVisualizationResponse(
            video_id=video_id,
            nodes=nvl_nodes,
            relationships=nvl_rels,
            total_nodes=len(nvl_nodes),
            total_relationships=len(nvl_rels),
            depth=depth,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get video visualization: {e}", exc_info=True)
        raise internal_error() from e


@router.post("/expand-subgraph")
async def expand_subgraph(
    request: ExpandSubgraphRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Expand a node's neighborhood for progressive lazy-load in the graph viewer.

    Returns additional NVL nodes and relationships around the given node.
    """
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        service = get_knowledge_graph_service()
        subgraph = service.expand_node_subgraph(
            node_id=request.node_id,
            hops=request.hops,
            max_nodes=request.max_nodes,
        )

        raw_nodes = subgraph.get("nodes", [])
        raw_rels = subgraph.get("relationships", [])

        nvl_nodes = [_raw_to_nvl_node(n) for n in raw_nodes]
        nvl_rels = [_raw_to_nvl_rel(r) for r in raw_rels]

        return {
            "center_node_id": request.node_id,
            "nodes": [n.model_dump(by_alias=True) for n in nvl_nodes],
            "relationships": [r.model_dump(by_alias=True) for r in nvl_rels],
            "total_nodes": len(nvl_nodes),
            "total_relationships": len(nvl_rels),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to expand subgraph: {e}", exc_info=True)
        raise internal_error() from e
