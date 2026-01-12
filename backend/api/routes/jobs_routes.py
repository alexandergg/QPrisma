"""
Jobs API Routes para QPrisma
Endpoints para gestión de jobs de procesamiento asíncrono con Celery.

Uso:
    from api.routes import jobs_router
    app.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Modelos
# =============================================================================


class JobStatus(str, Enum):
    """Estados posibles de un job"""

    PENDING = "pending"
    STARTED = "started"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"
    CANCELLED = "cancelled"


class ProcessingConfig(BaseModel):
    """Configuración para procesamiento de video"""

    max_frames: int = Field(default=100, ge=1, le=500, description="Máximo de frames a extraer")
    custom_prompt: str | None = Field(
        default=None, description="Prompt personalizado para análisis"
    )
    use_cache: bool = Field(default=True, description="Usar cache para frames similares")
    transcribe_audio: bool = Field(default=True, description="Transcribir audio con Whisper")
    index_content: bool = Field(default=True, description="Indexar para búsqueda (Knowledge Graph)")
    priority: int = Field(default=5, ge=1, le=10, description="Prioridad del job (1-10)")

    class Config:
        json_schema_extra = {
            "example": {
                "max_frames": 100,
                "custom_prompt": None,
                "use_cache": True,
                "transcribe_audio": True,
                "index_content": True,
                "priority": 5,
            }
        }


class JobSubmitRequest(BaseModel):
    """Request para enviar un job de procesamiento"""

    video_id: str = Field(description="ID único del video")
    blob_name: str = Field(description="Nombre del blob en Azure Storage")
    config: ProcessingConfig | None = Field(
        default=None, description="Configuración de procesamiento"
    )


class JobSubmitResponse(BaseModel):
    """Respuesta al enviar un job"""

    job_id: str = Field(description="ID del job para tracking")
    video_id: str
    status: JobStatus
    message: str
    estimated_time_seconds: int | None = Field(default=None, description="Tiempo estimado")


class JobStatusResponse(BaseModel):
    """Estado detallado de un job"""

    job_id: str
    video_id: str | None = None
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    stage: str
    message: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_time_seconds: float | None = None


class JobListResponse(BaseModel):
    """Lista de jobs"""

    total: int
    jobs: list[JobStatusResponse]


# =============================================================================
# Celery Integration
# =============================================================================


def get_celery_app():
    """Obtiene la instancia de Celery (lazy import)"""
    try:
        from tasks.celery_app import celery_app

        return celery_app
    except Exception as e:
        logger.error(f"Failed to import Celery: {e}")
        return None


def celery_state_to_job_status(state: str) -> JobStatus:
    """Convierte estado de Celery a JobStatus"""
    mapping = {
        "PENDING": JobStatus.PENDING,
        "STARTED": JobStatus.STARTED,
        "SUCCESS": JobStatus.SUCCESS,
        "FAILURE": JobStatus.FAILURE,
        "REVOKED": JobStatus.REVOKED,
        "RETRY": JobStatus.PROCESSING,
        "PROGRESS": JobStatus.PROCESSING,
    }
    return mapping.get(state, JobStatus.PROCESSING)


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/submit",
    response_model=JobSubmitResponse,
    summary="Enviar video para procesamiento async",
    description="""
    Envía un video a la cola de procesamiento de Celery.
    Retorna inmediatamente con un job_id para tracking.

    El procesamiento incluye:
    1. Descarga del video
    2. Extracción de frames
    3. Análisis con GPT-4V
    4. Generación de embeddings
    5. Transcripción de audio (opcional)
    6. Indexación para búsqueda (Knowledge Graph)
    """,
)
async def submit_job(request: JobSubmitRequest):
    """Envía un job de procesamiento a Celery"""
    celery_app = get_celery_app()
    if not celery_app:
        raise HTTPException(
            status_code=503,
            detail="Celery no disponible. Asegúrate de que el worker está corriendo.",
        )

    try:
        from tasks.video_tasks import process_video_pipeline

        # Preparar configuración
        config = request.config.model_dump() if request.config else {}

        # Enviar tarea a Celery
        result = process_video_pipeline.apply_async(
            args=[request.video_id, request.blob_name, config], priority=config.get("priority", 5)
        )

        # Estimar tiempo (muy aproximado)
        max_frames = config.get("max_frames", 20)
        estimated_time = max_frames * 3 + 30  # ~3 seg/frame + overhead

        logger.info(f"Job submitted: {result.id} for video {request.video_id}")

        return JobSubmitResponse(
            job_id=result.id,
            video_id=request.video_id,
            status=JobStatus.PENDING,
            message="Job enviado a la cola de procesamiento",
            estimated_time_seconds=estimated_time,
        )

    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Obtener estado de un job",
    description="Obtiene el estado actual de un job de procesamiento.",
)
async def get_job_status(job_id: str):
    """Obtiene el estado de un job"""
    celery_app = get_celery_app()
    if not celery_app:
        raise HTTPException(status_code=503, detail="Celery no disponible")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        # Obtener info adicional del cache si está disponible
        cache_info = None
        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            cache_info = await cache.get_job_status(job_id)
        except Exception:
            cache_info = None

        # Construir respuesta
        status = celery_state_to_job_status(result.state)
        progress = 0
        stage = "unknown"
        message = None
        error = None
        job_result = None

        if cache_info:
            progress = cache_info.get("progress", 0)
            stage = cache_info.get("stage", "processing")
            message = cache_info.get("message")
            error = cache_info.get("error")

        if result.state == "SUCCESS":
            status = JobStatus.SUCCESS
            progress = 100
            stage = "completed"
            job_result = result.result
        elif result.state == "FAILURE":
            status = JobStatus.FAILURE
            error = str(result.result) if result.result else "Unknown error"
            stage = "failed"

        return JobStatusResponse(
            job_id=job_id,
            video_id=cache_info.get("video_id") if cache_info else None,
            status=status,
            progress=progress,
            stage=stage,
            message=message,
            error=error,
            result=job_result,
        )

    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{job_id}/cancel",
    summary="Cancelar un job",
    description="Intenta cancelar un job en progreso.",
)
async def cancel_job(job_id: str):
    """Cancela un job en ejecución"""
    celery_app = get_celery_app()
    if not celery_app:
        raise HTTPException(status_code=503, detail="Celery no disponible")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        if result.state in ["PENDING", "STARTED", "RETRY"]:
            result.revoke(terminate=True)

            # Actualizar cache
            try:
                import asyncio

                from services.cache_service import get_cache_service

                cache = asyncio.get_event_loop().run_until_complete(get_cache_service())
                asyncio.get_event_loop().run_until_complete(
                    cache.set_job_status(
                        job_id,
                        {
                            "status": "cancelled",
                            "progress": 0,
                            "stage": "cancelled",
                            "message": "Job cancelado por usuario",
                        },
                    )
                )
            except:
                pass

            return {"job_id": job_id, "status": "cancelled", "message": "Job cancelado"}
        else:
            return {
                "job_id": job_id,
                "status": result.state.lower(),
                "message": f"No se puede cancelar job en estado {result.state}",
            }

    except Exception as e:
        logger.error(f"Failed to cancel job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{job_id}/result",
    summary="Obtener resultado de un job completado",
    description="Obtiene el resultado completo de un job que ha finalizado.",
)
async def get_job_result(job_id: str):
    """Obtiene el resultado de un job completado"""
    celery_app = get_celery_app()
    if not celery_app:
        raise HTTPException(status_code=503, detail="Celery no disponible")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        if result.state == "SUCCESS":
            return {"job_id": job_id, "status": "success", "result": result.result}
        elif result.state == "FAILURE":
            return {"job_id": job_id, "status": "failure", "error": str(result.result)}
        else:
            raise HTTPException(
                status_code=400, detail=f"Job aún en progreso (estado: {result.state})"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/",
    response_model=JobListResponse,
    summary="Listar jobs recientes",
    description="Lista los jobs recientes con su estado.",
)
async def list_jobs(status: JobStatus | None = None, limit: int = 20):
    """Lista jobs recientes"""
    # Obtener jobs del cache
    try:
        import asyncio

        from services.cache_service import get_cache_service

        cache = asyncio.get_event_loop().run_until_complete(get_cache_service())

        # Buscar jobs en cache
        pattern = f"{cache.config.key_prefix}:job_status:*"
        jobs = []

        if cache._use_memory_fallback:
            keys = asyncio.get_event_loop().run_until_complete(cache._memory_cache.keys(pattern))
        else:
            keys = []

            async def get_keys():
                async for key in cache._redis.scan_iter(match=pattern):
                    keys.append(key.decode() if isinstance(key, bytes) else key)

            asyncio.get_event_loop().run_until_complete(get_keys())

        for key in keys[:limit]:
            job_id = key.split(":")[-1]
            job_data = asyncio.get_event_loop().run_until_complete(cache.get_job_status(job_id))
            if job_data:
                job_status = JobStatus(job_data.get("status", "pending"))
                if status is None or job_status == status:
                    jobs.append(
                        JobStatusResponse(
                            job_id=job_id,
                            video_id=job_data.get("video_id"),
                            status=job_status,
                            progress=job_data.get("progress", 0),
                            stage=job_data.get("stage", "unknown"),
                            message=job_data.get("message"),
                            error=job_data.get("error"),
                        )
                    )

        return JobListResponse(total=len(jobs), jobs=jobs)

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return JobListResponse(total=0, jobs=[])


@router.get(
    "/stats/summary",
    summary="Estadísticas de jobs",
    description="Obtiene estadísticas resumidas de los jobs.",
)
async def get_jobs_stats():
    """Obtiene estadísticas de jobs"""
    celery_app = get_celery_app()

    stats = {"celery_available": celery_app is not None, "workers": [], "queues": {}}

    if celery_app:
        try:
            # Obtener info de workers
            inspect = celery_app.control.inspect()
            active = inspect.active() or {}
            reserved = inspect.reserved() or {}

            for worker_name in set(list(active.keys()) + list(reserved.keys())):
                worker_stats = {
                    "name": worker_name,
                    "active_tasks": len(active.get(worker_name, [])),
                    "reserved_tasks": len(reserved.get(worker_name, [])),
                }
                stats["workers"].append(worker_stats)

            # Info de colas
            try:
                from tasks.celery_app import celery_app as app

                with app.connection() as conn:
                    for queue in ["video_processing", "fast_tasks", "default"]:
                        try:
                            queue_info = conn.default_channel.queue_declare(
                                queue=queue, passive=True
                            )
                            stats["queues"][queue] = queue_info.message_count
                        except:
                            stats["queues"][queue] = 0
            except:
                pass

        except Exception as e:
            logger.warning(f"Failed to get Celery stats: {e}")

    return stats
