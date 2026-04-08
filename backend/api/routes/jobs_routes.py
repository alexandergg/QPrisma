"""
Jobs API Routes for QPrisma
Endpoints for managing asynchronous processing jobs with Celery.

Usage:
    from api.routes import jobs_router
    app.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
from core.errors import bad_request, internal_error, service_unavailable
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Modelos
# =============================================================================


class JobStatus(str, Enum):
    """Possible job states"""

    PENDING = "pending"
    STARTED = "started"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"
    CANCELLED = "cancelled"


class JobStatusResponse(BaseModel):
    """Detailed job status"""

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
    """List of jobs"""

    total: int
    jobs: list[JobStatusResponse]


# =============================================================================
# Celery Integration
# =============================================================================


def get_celery_app():
    """Gets the Celery instance (lazy import)"""
    try:
        from tasks.celery_app import celery_app

        return celery_app
    except Exception as e:
        logger.error(f"Failed to import Celery: {e}")
        return None


def celery_state_to_job_status(state: str) -> JobStatus:
    """Converts Celery state to JobStatus"""
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


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Gets the current status of a processing job.",
)
async def get_job_status(job_id: str, current_user: User = Depends(get_current_user)):
    """Gets job status"""
    celery_app = get_celery_app()
    if not celery_app:
        raise service_unavailable("Celery not available")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        # Get additional info from cache if available
        cache_info = None
        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            cache_info = await cache.get_job_status(job_id)
        except (ImportError, ConnectionError, KeyError) as e:
            logger.warning(f"Could not get cache info for job {job_id}: {e}")
            cache_info = None

        # Build response
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
        logger.error(f"Failed to get job status: {e}", exc_info=True)
        raise internal_error(detail="Processing operation failed") from e


@router.post(
    "/{job_id}/cancel",
    summary="Cancel a job",
    description="Attempts to cancel a job in progress.",
)
async def cancel_job(job_id: str, current_user: User = Depends(get_current_user)):
    """Cancels a running job"""
    celery_app = get_celery_app()
    if not celery_app:
        raise service_unavailable("Celery not available")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        if result.state in ["PENDING", "STARTED", "RETRY"]:
            result.revoke(terminate=True)

            # Update cache
            try:
                from services.cache_service import get_cache_service

                cache = await get_cache_service()
                await cache.set_job_status(
                    job_id,
                    {
                        "status": "cancelled",
                        "progress": 0,
                        "stage": "cancelled",
                        "message": "Job cancelled by user",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to update cache for cancelled job {job_id}: {e}")

            return {"job_id": job_id, "status": "cancelled", "message": "Job cancelled"}
        else:
            return {
                "job_id": job_id,
                "status": result.state.lower(),
                "message": f"Cannot cancel job in state {result.state}",
            }

    except Exception as e:
        logger.error(f"Failed to cancel job: {e}", exc_info=True)
        raise internal_error(detail="Processing operation failed") from e


@router.get(
    "/{job_id}/result",
    summary="Get completed job result",
    description="Gets the complete result of a completed job.",
)
async def get_job_result(job_id: str, current_user: User = Depends(get_current_user)):
    """Gets the result of a completed job"""
    celery_app = get_celery_app()
    if not celery_app:
        raise service_unavailable("Celery not available")

    try:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=celery_app)

        if result.state == "SUCCESS":
            return {"job_id": job_id, "status": "success", "result": result.result}
        elif result.state == "FAILURE":
            return {"job_id": job_id, "status": "failure", "error": str(result.result)}
        else:
            raise bad_request(f"Job still in progress (state: {result.state})")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job result: {e}", exc_info=True)
        raise internal_error(detail="Processing operation failed") from e


@router.get(
    "/",
    response_model=JobListResponse,
    summary="List recent jobs",
    description="Lists recent jobs with their status.",
)
async def list_jobs(
    status: JobStatus | None = None, limit: int = 20, current_user: User = Depends(get_current_user)
):
    """Lists recent jobs"""
    # Get jobs from cache
    try:
        from services.cache_service import get_cache_service

        cache = await get_cache_service()

        # Search jobs in cache
        pattern = f"{cache.config.key_prefix}:job_status:*"
        jobs = []

        if cache._use_memory_fallback:
            keys = await cache._memory_cache.keys(pattern)
        else:
            keys = []
            async for key in cache._redis.scan_iter(match=pattern):
                keys.append(key.decode() if isinstance(key, bytes) else key)

        for key in keys[:limit]:
            job_id = key.split(":")[-1]
            job_data = await cache.get_job_status(job_id)
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
    summary="Job statistics",
    description="Gets summary statistics of jobs.",
)
async def get_jobs_stats(current_user: User = Depends(get_current_user)):
    """Gets job statistics"""
    celery_app = get_celery_app()

    stats = {"celery_available": celery_app is not None, "workers": [], "queues": {}}

    if celery_app:
        try:
            # Get worker info
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

            # Queue info
            try:
                from tasks.celery_app import celery_app as app

                with app.connection() as conn:
                    for queue in ["video_processing", "fast_tasks", "default"]:
                        try:
                            queue_info = conn.default_channel.queue_declare(
                                queue=queue, passive=True
                            )
                            stats["queues"][queue] = queue_info.message_count
                        except Exception:
                            stats["queues"][queue] = 0
            except Exception as e:
                logger.warning(f"Failed to get queue stats: {e}")

        except Exception as e:
            logger.warning(f"Failed to get Celery stats: {e}")

    return stats
