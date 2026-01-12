"""
Cache API Routes para QPrisma
Endpoints para gestión y monitoreo del sistema de caching.

Uso:
    from api.routes import cache_router
    app.include_router(cache_router, prefix="/cache", tags=["Cache"])
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from models.cache_models import (
    CacheBackend,
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    CacheMetricsResponse,
    CacheSettings,
    JobStatusCache,
)
from services.cache_service import CacheService, get_cache_service

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# Dependencia del Cache Service
# =============================================================================


async def get_cache() -> CacheService:
    """Dependency para obtener el CacheService singleton"""
    return await get_cache_service()


# =============================================================================
# Endpoints de Métricas
# =============================================================================


@router.get(
    "/metrics",
    response_model=CacheMetricsResponse,
    summary="Obtener métricas del cache",
    description="""
    Retorna métricas de rendimiento del sistema de cache:
    - Hits/Misses y hit rate
    - Llamadas a API ahorradas
    - Estimación de costos ahorrados
    """,
)
async def get_cache_metrics(cache: CacheService = Depends(get_cache)):
    """Obtiene métricas actuales del cache"""
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
    summary="Resetear métricas del cache",
    description="Resetea los contadores de hits, misses y ahorros a cero.",
)
async def reset_cache_metrics(cache: CacheService = Depends(get_cache)):
    """Resetea las métricas del cache"""
    cache.reset_metrics()
    return {"message": "Metrics reset successfully"}


@router.get(
    "/health",
    summary="Health check del cache",
    description="Verifica el estado de conexión del cache.",
)
async def cache_health(cache: CacheService = Depends(get_cache)):
    """Health check del sistema de cache"""
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
# Endpoints de Invalidación
# =============================================================================


@router.post(
    "/invalidate",
    response_model=CacheInvalidateResponse,
    summary="Invalidar cache",
    description="""
    Invalida (elimina) entradas del cache según el criterio especificado:
    - Por patrón glob
    - Por video_id
    - Por tipo de cache
    - Todo el cache (clear_all=true)
    """,
)
async def invalidate_cache(
    request: CacheInvalidateRequest, cache: CacheService = Depends(get_cache)
):
    """Invalida cache según criterios"""
    keys_deleted = 0

    try:
        if request.clear_all:
            # Limpiar todo (peligroso)
            logger.warning("Clearing ALL cache - requested by user")
            success = await cache.clear_all()
            return CacheInvalidateResponse(
                success=success,
                keys_deleted=-1,  # Unknown
                message="All cache cleared" if success else "Failed to clear cache",
            )

        if request.video_id:
            # Invalidar por video
            keys_deleted = await cache.invalidate_video(request.video_id)
            return CacheInvalidateResponse(
                success=True,
                keys_deleted=keys_deleted,
                message=f"Invalidated cache for video {request.video_id}",
            )

        if request.pattern:
            # Invalidar por patrón
            keys_deleted = await cache.invalidate_by_pattern(request.pattern)
            return CacheInvalidateResponse(
                success=True,
                keys_deleted=keys_deleted,
                message=f"Invalidated {keys_deleted} keys matching pattern",
            )

        if request.cache_type:
            # Invalidar por tipo
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
        logger.error(f"Cache invalidation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/video/{video_id}",
    response_model=CacheInvalidateResponse,
    summary="Invalidar cache de un video",
    description="Elimina todas las entradas de cache relacionadas con un video específico.",
)
async def invalidate_video_cache(video_id: str, cache: CacheService = Depends(get_cache)):
    """Invalida cache de un video específico"""
    keys_deleted = await cache.invalidate_video(video_id)

    return CacheInvalidateResponse(
        success=True,
        keys_deleted=keys_deleted,
        message=f"Invalidated {keys_deleted} cache entries for video {video_id}",
    )


# =============================================================================
# Endpoints de Estado de Jobs
# =============================================================================


@router.get(
    "/job/{job_id}",
    response_model=JobStatusCache | None,
    summary="Obtener estado de job desde cache",
    description="Recupera el estado de un job de procesamiento desde el cache.",
)
async def get_job_status(job_id: str, cache: CacheService = Depends(get_cache)):
    """Obtiene estado de job desde cache"""
    status = await cache.get_job_status(job_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found in cache")

    return status


@router.put(
    "/job/{job_id}",
    summary="Actualizar estado de job en cache",
    description="Actualiza el estado de un job de procesamiento en el cache.",
)
async def update_job_status(
    job_id: str,
    progress: int,
    stage: str,
    message: str | None = None,
    cache: CacheService = Depends(get_cache),
):
    """Actualiza estado de job en cache"""
    success = await cache.update_job_progress(
        job_id=job_id, progress=progress, stage=stage, message=message
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update job status")

    return {"message": "Job status updated", "job_id": job_id, "progress": progress}


# =============================================================================
# Configuración
# =============================================================================


@router.get(
    "/config",
    response_model=CacheSettings,
    summary="Obtener configuración del cache",
    description="Retorna la configuración actual del sistema de cache.",
)
async def get_cache_config(cache: CacheService = Depends(get_cache)):
    """Obtiene configuración actual del cache"""
    return CacheSettings(
        enabled=True,
        redis_url=cache.redis_url,
        key_prefix=cache.config.key_prefix,
        similarity_threshold=cache.config.similarity_threshold,
        max_memory_items=cache.config.max_memory_items,
    )
