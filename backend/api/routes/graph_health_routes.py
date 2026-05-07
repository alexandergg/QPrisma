"""Knowledge Graph health and statistics endpoints."""

import logging

from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from core.degraded import DegradationImpact, record_degraded_operation
from core.exceptions import internal_error
from models.graph_models import GraphStats
from models.graph_route_schemas import GraphHealthResponse
from models.user import User
from services.graph_route_service import GraphRouteService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_async_graph_service():
    from api.routes import graph_routes

    return graph_routes.get_async_graph_service()


def get_graph_route_service():
    from api.routes import graph_routes

    return graph_routes.get_graph_route_service()


@router.get("/health", response_model=GraphHealthResponse)
async def graph_health_check(current_user: User = Depends(get_current_user)):
    """Verify the connection status with Neo4j."""
    try:
        service = get_async_graph_service()
        svc: GraphRouteService = get_graph_route_service()
        result = svc.check_graph_health(service.sync_service)
        uri = result.uri if current_user.is_superuser else "redacted"
        return GraphHealthResponse(
            status=result.status,
            connected=result.connected,
            uri=uri,
            message=result.message,
        )
    except Exception as e:
        logger.error("Graph health check failed: %s", e, exc_info=True)
        return GraphHealthResponse(
            status="error",
            connected=False,
            uri="unknown",
            message="Unexpected error during health check",
        )


@router.get("/stats", response_model=GraphStats)
async def get_graph_stats(current_user: User = Depends(get_current_user)):
    """Get Knowledge Graph statistics scoped to the caller unless superuser."""
    try:
        service = get_async_graph_service()
        scoped_user_id = None if current_user.is_superuser else current_user.id

        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            stats_key = f"stats:{scoped_user_id or 'global'}"
            cached = await cache.get_graph_query(stats_key)
            if cached:
                return GraphStats(**cached)
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="graph",
                operation="stats_cache_read",
                impact=DegradationImpact.CACHE_READ,
                exc=exc,
                level=logging.DEBUG,
            )
            cache = None

        stats = await service.get_stats(user_id=scoped_user_id)

        if cache is not None:
            try:
                await cache.set_graph_query(stats_key, stats.model_dump(mode="json"), ttl=120)
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="graph",
                    operation="stats_cache_write",
                    impact=DegradationImpact.CACHE_WRITE,
                    exc=exc,
                    level=logging.DEBUG,
                )

        return stats
    except Exception as e:
        logger.error("Failed to get graph stats: %s", e, exc_info=True)
        raise internal_error() from e
