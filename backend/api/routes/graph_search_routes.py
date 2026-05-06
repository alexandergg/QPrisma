"""Knowledge Graph search, expansion, timeline, and video graph endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import (
    get_current_user,
)
from core.degraded import DegradationImpact, record_degraded_operation
from core.exceptions import internal_error, not_found_error
from models.graph_models import GraphSearchResponse
from models.graph_route_schemas import (
    ContextExpansionRequest,
    ContextExpansionResponse,
    CrossVideoSearchRequest,
    CrossVideoSearchResponse,
    EntityTimelineRequest,
    EntityTimelineResponse,
    HybridSearchRequest,
)
from models.user import User
from services.graph_route_service import GraphRouteService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_async_graph_service():
    from api.routes import graph_routes

    return graph_routes.get_async_graph_service()


def get_graph_node_media_or_404(node_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_graph_node_media_or_404(node_id, current_user)


def get_graph_route_service():
    from api.routes import graph_routes

    return graph_routes.get_graph_route_service()


def get_graph_search_service():
    from api.routes import graph_routes

    return graph_routes.get_graph_search_service()


def get_media_or_404(media_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_media_or_404(media_id, current_user)


@router.post("/search/hybrid", response_model=GraphSearchResponse)
async def hybrid_search(
    request: HybridSearchRequest, current_user: User = Depends(get_current_user)
):
    """Hybrid search combining vector, full-text, graph proximity, and temporal signals."""
    try:
        if request.video_id:
            get_media_or_404(request.video_id, current_user)
        if request.video_ids:
            for video_id in request.video_ids:
                get_media_or_404(video_id, current_user)

        search_service = get_graph_search_service()
        time_range = GraphRouteService.build_time_range(request.time_start, request.time_end)

        return await search_service.hybrid_search(
            query_text=request.query,
            node_types=request.node_types,
            video_id=request.video_id,
            video_ids=request.video_ids,
            user_id=current_user.id,
            time_range=time_range,
            limit=request.limit,
            expansion_hops=request.expansion_hops if request.use_graph_expansion else 0,
            use_reranking=request.use_reranking,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Hybrid search failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/search/cross-video", response_model=CrossVideoSearchResponse)
async def cross_video_search(
    request: CrossVideoSearchRequest, current_user: User = Depends(get_current_user)
):
    """Find similar nodes in other videos within the caller's accessible scope."""
    try:
        get_graph_node_media_or_404(request.reference_node_id, current_user)
        search_service = get_graph_search_service()
        scoped_user_id = None if current_user.is_superuser else current_user.id

        similar_nodes = await search_service.find_similar_across_videos(
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
        logger.error("Cross-video search failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/expand", response_model=ContextExpansionResponse)
async def expand_context(
    request: ContextExpansionRequest, current_user: User = Depends(get_current_user)
):
    """Expand graph context around a node for RAG."""
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        service = get_async_graph_service()
        result = await service.expand_context(
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
        logger.error("Context expansion failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/timeline", response_model=EntityTimelineResponse)
async def get_entity_timeline(
    request: EntityTimelineRequest, current_user: User = Depends(get_current_user)
):
    """Get the timeline of entity appearances in a video."""
    try:
        get_media_or_404(request.video_id, current_user)
        service = get_async_graph_service()
        occurrences = await service.get_entity_timeline(
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
        logger.error("Failed to get entity timeline: %s", e, exc_info=True)
        raise internal_error() from e


@router.get("/video/{video_id}")
async def get_video_graph(video_id: str, current_user: User = Depends(get_current_user)):
    """Get the complete Knowledge Graph subgraph for a video."""
    try:
        get_media_or_404(video_id, current_user)
        svc: GraphRouteService = get_graph_route_service()
        scoped_user_id = None if current_user.is_superuser else current_user.id

        cache = None
        cache_key = f"video_graph:{video_id}:{scoped_user_id or 'global'}"
        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            cached = await cache.get_graph_query(cache_key)
            if cached:
                return cached
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="graph",
                operation="video_graph_cache_read",
                impact=DegradationImpact.CACHE_READ,
                exc=exc,
                level=logging.DEBUG,
            )
            cache = None

        data = svc.get_video_graph_data(video_id, user_id=scoped_user_id)

        if data.error:
            raise not_found_error("Video", video_id)

        result = {
            "video": data.video,
            "scenes": data.scenes,
            "total_scenes": data.total_scenes,
            "graph_stats": data.graph_stats,
        }

        if cache is not None:
            try:
                await cache.set_graph_query(cache_key, result)
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="graph",
                    operation="video_graph_cache_write",
                    impact=DegradationImpact.CACHE_WRITE,
                    exc=exc,
                    level=logging.DEBUG,
                )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get video graph: %s", e, exc_info=True)
        raise internal_error() from e


@router.delete("/video/{video_id}")
async def delete_video_graph(video_id: str, current_user: User = Depends(get_current_user)):
    """Delete all graph data associated with a video."""
    try:
        get_media_or_404(video_id, current_user)
        service = get_async_graph_service()
        deleted_count = await service.delete_video_graph(video_id)

        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            await cache.invalidate_video(video_id)
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="graph",
                operation="delete_video_cache_invalidation",
                impact=DegradationImpact.CACHE_INVALIDATION,
                exc=exc,
                level=logging.DEBUG,
            )

        return {
            "status": "success",
            "video_id": video_id,
            "deleted_nodes": deleted_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete video graph: %s", e, exc_info=True)
        raise internal_error() from e
