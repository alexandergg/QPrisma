"""Knowledge Graph API router aggregator for QPrisma."""

from fastapi import APIRouter

from api.dependencies import (
    get_async_graph_service,
    get_graph_node_media_or_404,
    get_graph_route_service,
    get_graph_search_service,
    get_hierarchical_context_service,
    get_media_or_404,
    require_superuser,
)
from api.routes.graph_admin_routes import clear_all_graph_data
from api.routes.graph_admin_routes import router as admin_router
from api.routes.graph_embedding_routes import generate_embeddings, get_embedding_stats
from api.routes.graph_embedding_routes import router as embedding_router
from api.routes.graph_health_routes import get_graph_stats, graph_health_check
from api.routes.graph_health_routes import router as health_router
from api.routes.graph_hierarchy_routes import (
    drill_down_search,
    get_hierarchy_path,
    get_hierarchy_stats,
    load_children,
    process_video_hierarchy,
)
from api.routes.graph_hierarchy_routes import router as hierarchy_router
from api.routes.graph_search_routes import (
    cross_video_search,
    delete_video_graph,
    expand_context,
    get_entity_timeline,
    get_video_graph,
    hybrid_search,
)
from api.routes.graph_search_routes import router as search_router
from api.routes.graph_visualization_routes import (
    expand_subgraph,
    get_video_visualization,
)
from api.routes.graph_visualization_routes import router as visualization_router
from services.embedding_service import get_embedding_service
from services.graph_route_service import GraphRouteService

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])

router.include_router(health_router)
router.include_router(search_router)
router.include_router(embedding_router)
router.include_router(hierarchy_router)
router.include_router(admin_router)
router.include_router(visualization_router)

__all__ = [
    "clear_all_graph_data",
    "cross_video_search",
    "delete_video_graph",
    "drill_down_search",
    "expand_context",
    "expand_subgraph",
    "generate_embeddings",
    "get_embedding_stats",
    "get_async_graph_service",
    "get_embedding_service",
    "get_entity_timeline",
    "get_graph_stats",
    "get_graph_node_media_or_404",
    "get_graph_route_service",
    "get_graph_search_service",
    "get_hierarchical_context_service",
    "get_hierarchy_path",
    "get_hierarchy_stats",
    "get_media_or_404",
    "get_video_graph",
    "get_video_visualization",
    "GraphRouteService",
    "graph_health_check",
    "hybrid_search",
    "load_children",
    "process_video_hierarchy",
    "require_superuser",
    "router",
]
