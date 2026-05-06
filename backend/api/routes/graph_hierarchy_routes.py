"""Hierarchical Knowledge Graph endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import (
    get_current_user,
)
from core.degraded import DegradationImpact, record_degraded_operation
from core.exceptions import internal_error, not_found_error
from models.graph_models import NodeType
from models.graph_route_schemas import (
    DrillDownSearchRequest,
    DrillDownSearchResponse,
    HierarchyLevelResponse,
    HierarchyPathResponse,
    HierarchyStatsResponse,
    LoadChildrenRequest,
    LoadChildrenResponse,
    ProcessHierarchyRequest,
    ProcessHierarchyResponse,
)
from models.user import User
from services.graph_route_service import GraphRouteService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_graph_node_media_or_404(node_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_graph_node_media_or_404(node_id, current_user)


def get_graph_route_service():
    from api.routes import graph_routes

    return graph_routes.get_graph_route_service()


def get_hierarchical_context_service():
    from api.routes import graph_routes

    return graph_routes.get_hierarchical_context_service()


def get_media_or_404(media_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_media_or_404(media_id, current_user)


@router.post("/hierarchy/process", response_model=ProcessHierarchyResponse)
async def process_video_hierarchy(
    request: ProcessHierarchyRequest,
    current_user: User = Depends(get_current_user),
):
    """Process a video into the hierarchical graph representation."""
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

        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            await cache.invalidate_video(request.video_id)
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="graph",
                operation="hierarchy_cache_invalidation",
                impact=DegradationImpact.CACHE_INVALIDATION,
                exc=exc,
                level=logging.DEBUG,
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
        logger.error("Hierarchy processing failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/hierarchy/search/drill-down", response_model=DrillDownSearchResponse)
async def drill_down_search(
    request: DrillDownSearchRequest, current_user: User = Depends(get_current_user)
):
    """Run hierarchical drill-down search."""
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
        logger.error("Drill-down search failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/hierarchy/children", response_model=LoadChildrenResponse)
async def load_children(
    request: LoadChildrenRequest, current_user: User = Depends(get_current_user)
):
    """Lazy-load children of a hierarchy node."""
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        hierarchy_service = get_hierarchical_context_service()

        children = await hierarchy_service.load_children(
            node_id=request.node_id,
            node_type=request.node_type,
            limit=request.limit + 1,
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
        logger.error("Load children failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.get("/hierarchy/stats/{video_id}", response_model=HierarchyStatsResponse)
async def get_hierarchy_stats(video_id: str, current_user: User = Depends(get_current_user)):
    """Get hierarchy statistics for a video."""
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
        logger.error("Get hierarchy stats failed: %s", e, exc_info=True)
        raise internal_error() from e


@router.get("/hierarchy/path/{node_id}", response_model=HierarchyPathResponse)
async def get_hierarchy_path(
    node_id: str,
    node_type: NodeType = Query(NodeType.SCENE),
    current_user: User = Depends(get_current_user),
):
    """Get the full hierarchy path from the root video to a node."""
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
        logger.error("Get hierarchy path failed: %s", e, exc_info=True)
        raise internal_error() from e
