"""
Cache API Routes for QPrisma
Endpoints for cache system management and monitoring.

Usage:
    from api.routes import cache_router
    app.include_router(cache_router, prefix="/cache", tags=["Cache"])
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user
from models.cache_models import (
    CacheBackend,
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    CacheMetricsResponse,
    CacheSettings,
    JobStatusCache,
)
from models.user import User
from services.cache_service import CacheService, get_cache_service

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# Cache Service Dependency
# =============================================================================


async def get_cache() -> CacheService:
    """Dependency to obtain the CacheService singleton"""
    return await get_cache_service()


# =============================================================================
# Metrics Endpoints
# =============================================================================


@router.get(
    "/metrics",
    response_model=CacheMetricsResponse,
    summary="Get cache metrics",
    description="""
    Returns performance metrics for the cache system:
    - Hits/Misses and hit rate
    - API calls saved
    - Estimated cost savings
    """,
)
async def get_cache_metrics(
    current_user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache)
):
    """Gets current cache metrics"""
    metrics = cache.get_metrics()

    return CacheMetricsResponse(
        connected=metrics.get("connected", False),
        backend=CacheBackend(metrics.get("backend", "disabled")),
        hits=metrics.get("hits", 0),
        misses=metrics.get("misses", 0),
        errors=metrics.get("errors", 0),
        hit_rate=metrics.get("hit_rate", "0.00%"),
        bytes_saved=metrics.get("bytes_saved", 0),
        api_calls_saved=metrics.get("api_calls_saved", 0),
        estimated_cost_saved=metrics.get("estimated_cost_saved", "$0.00"),
    )


@router.post(
    "/metrics/reset",
    summary="Reset cache metrics",
    description="Resets the hits, misses, and savings counters to zero.",
)
async def reset_cache_metrics(
    current_user: User = Depends(get_current_user), cache: CacheService = Depends(get_cache)
):
    """Resets cache metrics"""
    cache.reset_metrics()
    return {"message": "Metrics reset successfully"}


@router.get(
    "/health",
    summary="Cache health check",
    description="Verifies the connection status of the cache.",
)
async def cache_health(cache: CacheService = Depends(get_cache)):
    """Health check for the cache system"""
    metrics = cache.get_metrics()

    return {
        "status": "healthy" if metrics.get("connected") else "degraded",
        "backend": metrics.get("backend", "unknown"),
        "connected": metrics.get("connected", False),
        "message": (
            "Cache operational" if metrics.get("connected") else "Using fallback memory cache"
        ),
    }


# =============================================================================
# Invalidation Endpoints
# =============================================================================


@router.post(
    "/invalidate",
    response_model=CacheInvalidateResponse,
    summary="Invalidate cache",
    description="""
    Invalidates (removes) cache entries according to the specified criteria:
    - By glob pattern
    - By video_id
    - By cache type
    - Entire cache (clear_all=true)
    """,
)
async def invalidate_cache(
    request: CacheInvalidateRequest,
    current_user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    """Invalidates cache according to criteria"""
    keys_deleted = 0

    try:
        if request.clear_all:
            # Clear everything (dangerous)
            logger.warning("Clearing ALL cache - requested by user")
            success = await cache.clear_all()
            return CacheInvalidateResponse(
                success=success,
                keys_deleted=-1,  # Unknown
                message="All cache cleared" if success else "Failed to clear cache",
            )

        if request.video_id:
            # Invalidate by video
            keys_deleted = await cache.invalidate_video(request.video_id)
            return CacheInvalidateResponse(
                success=True,
                keys_deleted=keys_deleted,
                message=f"Invalidated cache for video {request.video_id}",
            )

        if request.pattern:
            # Invalidate by pattern
            keys_deleted = await cache.invalidate_by_pattern(request.pattern)
            return CacheInvalidateResponse(
                success=True,
                keys_deleted=keys_deleted,
                message=f"Invalidated {keys_deleted} keys matching pattern",
            )

        if request.cache_type:
            # Invalidate by type
            pattern = f"{cache.config.key_prefix}:{request.cache_type.value}:*"
            keys_deleted = await cache.invalidate_by_pattern(pattern)
            return CacheInvalidateResponse(
                success=True,
                keys_deleted=keys_deleted,
                message=f"Invalidated all {request.cache_type.value} entries",
            )

        return CacheInvalidateResponse(
            success=False, keys_deleted=0, message="No invalidation criteria specified"
        )

    except Exception as e:
        logger.error(f"Cache invalidation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Cache operation failed") from e


@router.delete(
    "/video/{video_id}",
    response_model=CacheInvalidateResponse,
    summary="Invalidate cache for a video",
    description="Removes all cache entries related to a specific video.",
)
async def invalidate_video_cache(
    video_id: str,
    current_user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache),
):
    """Invalidates cache for a specific video"""
    keys_deleted = await cache.invalidate_video(video_id)

    return CacheInvalidateResponse(
        success=True,
        keys_deleted=keys_deleted,
        message=f"Invalidated {keys_deleted} cache entries for video {video_id}",
    )


# =============================================================================
# Job Status Endpoints
# =============================================================================


@router.get(
    "/job/{job_id}",
    response_model=JobStatusCache | None,
    summary="Get job status from cache",
    description="Retrieves the status of a processing job from the cache.",
)
async def get_job_status(job_id: str, cache: CacheService = Depends(get_cache)):
    """Gets job status from cache"""
    status = await cache.get_job_status(job_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found in cache")

    return status


@router.put(
    "/job/{job_id}",
    summary="Update job status in cache",
    description="Updates the status of a processing job in the cache.",
)
async def update_job_status(
    job_id: str,
    progress: int,
    stage: str,
    message: str | None = None,
    cache: CacheService = Depends(get_cache),
):
    """Updates job status in cache"""
    success = await cache.update_job_progress(
        job_id=job_id, progress=progress, stage=stage, message=message
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update job status")

    return {"message": "Job status updated", "job_id": job_id, "progress": progress}


# =============================================================================
# Configuration
# =============================================================================


@router.get(
    "/config",
    response_model=CacheSettings,
    summary="Get cache configuration",
    description="Returns the current configuration of the cache system.",
)
async def get_cache_config(cache: CacheService = Depends(get_cache)):
    """Gets current cache configuration"""
    return CacheSettings(
        enabled=True,
        redis_url=cache.redis_url,
        key_prefix=cache.config.key_prefix,
        similarity_threshold=cache.config.similarity_threshold,
        max_memory_items=cache.config.max_memory_items,
    )
