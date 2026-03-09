"""
Batch API Routes

Endpoints for Azure OpenAI Batch API management.
Uses Global Batch deployments for 50% cost savings.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user, get_video_processor
from models.api_schemas import BatchStatusResponse, CostEstimateResponse
from models.user import User
from services.batch_processor import BatchProcessor
from services.database_service import get_database_service

router = APIRouter(prefix="/batch", tags=["Batch API"])
logger = logging.getLogger(__name__)


# =============================================================================
# Routes
# =============================================================================


@router.get("/status/{azure_batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    azure_batch_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get status of a batch job.
    """
    processor = get_video_processor()
    db = get_database_service()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        batch_proc = BatchProcessor(processor.openai_client)
        status = batch_proc.check_batch_status(azure_batch_id)

        # Try to get from database for additional info
        batch_job = db.get_batch_job_by_azure_id(azure_batch_id)

        total = status["request_counts"]["total"]
        completed = status["request_counts"]["completed"]

        return BatchStatusResponse(
            azure_batch_id=azure_batch_id,
            status=status["status"],
            total_requests=total,
            completed_requests=completed,
            failed_requests=status["request_counts"]["failed"],
            progress_percent=round((completed / max(total, 1)) * 100, 1),
            estimated_cost=batch_job.estimated_cost if batch_job else None,
            created_at=(
                batch_job.created_at.isoformat() if batch_job and batch_job.created_at else None
            ),
            completed_at=(
                batch_job.completed_at.isoformat() if batch_job and batch_job.completed_at else None
            ),
        )

    except Exception as e:
        logger.error(
            f"Batch status check failed for azure_batch_id={azure_batch_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Batch operation failed")


@router.get("/jobs")
async def list_batch_jobs(
    status: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """
    List batch jobs for the current user.
    """
    db = get_database_service()

    try:
        jobs = db.get_batch_jobs_by_user(current_user.id, status=status, limit=limit)
        return {
            "jobs": [job.to_dict() for job in jobs],
            "total": len(jobs),
        }
    except Exception as e:
        logger.error(f"Failed to list batch jobs for user={current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Batch operation failed")


@router.post("/cancel/{azure_batch_id}")
async def cancel_batch_job(
    azure_batch_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel an in-progress batch job.
    """
    processor = get_video_processor()
    db = get_database_service()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        batch_proc = BatchProcessor(processor.openai_client)

        # Check current status
        batch_job = db.get_batch_job_by_azure_id(azure_batch_id)
        if batch_job and batch_job.status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot cancel job with status: {batch_job.status}"
            )

        batch_proc.cancel_batch(azure_batch_id)

        db.update_batch_job_by_azure_id(
            azure_batch_id,
            {
                "status": "cancelled",
                "completed_at": datetime.now(UTC),
            },
        )

        return {"azure_batch_id": azure_batch_id, "status": "cancelled"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch cancel failed for azure_batch_id={azure_batch_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Batch operation failed")


@router.get("/cost-summary")
async def get_cost_summary(current_user: User = Depends(get_current_user)):
    """
    Get cost summary for batch processing.
    Shows total costs and estimated savings.
    """
    db = get_database_service()

    try:
        summary = db.get_batch_cost_summary(user_id=current_user.id)
        return summary
    except Exception as e:
        logger.error(f"Batch cost summary failed for user={current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Batch operation failed")


@router.get("/estimate", response_model=CostEstimateResponse)
async def estimate_batch_cost(frame_count: int):
    """
    Estimate processing cost for a given number of frames.
    """
    if frame_count < 1:
        raise HTTPException(status_code=400, detail="frame_count must be >= 1")

    # Use BatchProcessor for estimation (no client needed)
    estimated_tokens = frame_count * 1150  # ~1000 input + 150 output
    cost = (frame_count * 1000 / 1000) * 0.0025 + (frame_count * 150 / 1000) * 0.01

    return CostEstimateResponse(
        frame_count=frame_count,
        estimated_tokens=estimated_tokens,
        estimated_cost_usd=round(cost, 4),
        savings_vs_regular_usd=round(cost, 4),  # 50% savings = same amount
    )
