"""Hierarchical Knowledge Graph endpoints."""

import logging
import sys

from fastapi import APIRouter, Depends, HTTPException, Query

from api import dependencies as api_dependencies
from api.dependencies import (
    get_current_user,
)
from api.openapi_responses import (
    CONFLICT_RESPONSES,
    OWNER_SCOPED_RESPONSES,
    SERVICE_RESPONSES,
    merge_responses,
)
from core.degraded import DegradationImpact, record_degraded_operation
from core.errors import conflict
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


def _graph_route_facade(name: str):
    """Resolve graph route patch points without importing the graph route aggregator."""
    graph_routes = sys.modules.get("api.routes.graph_routes")
    if graph_routes is not None:
        patched = getattr(graph_routes, name, None)
        if patched is not None:
            return patched
    return getattr(api_dependencies, name)


def get_graph_node_media_or_404(node_id: str, current_user: User):
    return _graph_route_facade("get_graph_node_media_or_404")(node_id, current_user)


def get_graph_route_service():
    return _graph_route_facade("get_graph_route_service")()


def get_hierarchical_context_service():
    return _graph_route_facade("get_hierarchical_context_service")()


def get_media_or_404(media_id: str, current_user: User):
    return _graph_route_facade("get_media_or_404")(media_id, current_user)


def get_user_media_ids(current_user: User, *, processed_only: bool = False) -> list[str]:
    return _graph_route_facade("get_user_media_ids")(current_user, processed_only=processed_only)


def _server_managed_video_path(media) -> str | None:
    """Resolve a path from server-managed media metadata, never from client input."""
    for metadata in (
        getattr(media, "processing_result", None) or {},
        getattr(media, "video_metadata", None) or {},
    ):
        for key in ("local_video_path", "video_path", "source_video_path"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


@router.post(
    "/hierarchy/process",
    response_model=ProcessHierarchyResponse,
    summary="Process an owned video hierarchy",
    description=(
        "Process an authenticated user's video into the hierarchical graph representation. "
        "The API resolves server-managed media artifacts from the owned media record and does "
        "not trust client-supplied filesystem paths."
    ),
    responses=merge_responses(OWNER_SCOPED_RESPONSES, CONFLICT_RESPONSES, SERVICE_RESPONSES),
)
async def process_video_hierarchy(
    request: ProcessHierarchyRequest,
    current_user: User = Depends(get_current_user),
):
    """Process a video into the hierarchical graph representation."""
    try:
        media = get_media_or_404(request.video_id, current_user)
        video_path = _server_managed_video_path(media)
        if not video_path:
            raise conflict(
                "Hierarchy processing requires a server-managed local video artifact; "
                "client-supplied video_path values are not accepted."
            )

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
            video_path=video_path, video_metadata=video_metadata
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


@router.post(
    "/hierarchy/search/drill-down",
    response_model=DrillDownSearchResponse,
    summary="Run owner-scoped hierarchical drill-down search",
    description=(
        "Run semantic drill-down search over hierarchy nodes visible to the authenticated user. "
        "Non-superusers are scoped to their own media when `video_id` is omitted."
    ),
    responses=merge_responses(OWNER_SCOPED_RESPONSES, SERVICE_RESPONSES),
)
async def drill_down_search(
    request: DrillDownSearchRequest, current_user: User = Depends(get_current_user)
):
    """Run hierarchical drill-down search."""
    try:
        allowed_video_ids: list[str] | None = None
        if request.video_id:
            get_media_or_404(request.video_id, current_user)
            if not current_user.is_superuser:
                allowed_video_ids = [request.video_id]
        elif not current_user.is_superuser:
            allowed_video_ids = get_user_media_ids(current_user, processed_only=True)
            if not allowed_video_ids:
                return DrillDownSearchResponse(
                    query=request.query,
                    results=[],
                    total_results=0,
                    levels_traversed=[],
                )

        hierarchy_service = get_hierarchical_context_service()

        results = await hierarchy_service.drill_down_search(
            query_text=request.query,
            video_id=request.video_id,
            allowed_video_ids=allowed_video_ids,
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
