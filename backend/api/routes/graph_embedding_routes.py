"""Knowledge Graph embedding management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import (
    get_current_user,
    require_superuser,
)
from core.degraded import DegradationImpact, record_degraded_operation
from core.exceptions import internal_error
from models.graph_route_schemas import (
    EmbeddingStatsResponse,
    GenerateEmbeddingsRequest,
    GenerateEmbeddingsResponse,
)
from models.user import User
from services.graph_route_service import GraphRouteService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_embedding_service():
    from api.routes import graph_routes

    return graph_routes.get_embedding_service()


def get_graph_search_service():
    from api.routes import graph_routes

    return graph_routes.get_graph_search_service()


def get_media_or_404(media_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_media_or_404(media_id, current_user)


@router.post("/embeddings/generate", response_model=GenerateEmbeddingsResponse)
async def generate_embeddings(
    request: GenerateEmbeddingsRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate embeddings in bulk for existing graph nodes."""
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

        if request.video_id:
            try:
                from services.cache_service import get_cache_service

                cache = await get_cache_service()
                await cache.invalidate_video(request.video_id)
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="graph",
                    operation="embedding_cache_invalidation",
                    impact=DegradationImpact.CACHE_INVALIDATION,
                    exc=exc,
                    level=logging.DEBUG,
                )

        return GenerateEmbeddingsResponse(
            node_type=request.node_type.value,
            embeddings_generated=count,
            video_id=request.video_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate embeddings: %s", e, exc_info=True)
        raise internal_error() from e


@router.get("/embeddings/stats", response_model=EmbeddingStatsResponse)
async def get_embedding_stats(_admin_user: User = Depends(require_superuser)):
    """Get global embedding service statistics."""
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
        logger.error("Failed to get embedding stats: %s", e, exc_info=True)
        raise internal_error() from e
