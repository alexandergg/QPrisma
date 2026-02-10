"""
Storage Tiering API Routes

Endpoints for managing Azure Blob Storage tiers:
- Check current tier of videos
- Change tier manually
- Rehydrate archived videos
- Get tier recommendations
- Generate lifecycle policy
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user, get_media_or_404
from models.user import User
from services.database_service import get_database_service
from services.storage_tiering_service import (
    RehydratePriority,
    StorageTier,
    get_storage_tiering_service,
)

router = APIRouter(prefix="/storage", tags=["storage-tiering"])


# =============================================================================
# Request/Response Models
# =============================================================================


class ChangeTierRequest(BaseModel):
    """Request to change storage tier."""

    target_tier: StorageTier
    rehydrate_priority: RehydratePriority = RehydratePriority.STANDARD


class RehydrateRequest(BaseModel):
    """Request to rehydrate an archived video."""

    priority: RehydratePriority = RehydratePriority.STANDARD
    target_tier: StorageTier = StorageTier.HOT


class LifecyclePolicyRequest(BaseModel):
    """Request to generate lifecycle policy."""

    cool_days: int = 30
    cold_days: int = 90
    archive_days: int = 180
    prefix_filter: str = "videos/"


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health")
async def storage_health():
    """Check storage tiering service health."""
    service = get_storage_tiering_service()

    if service.blob_service:
        return {
            "status": "healthy",
            "container": service.container_name,
            "service": "storage_tiering",
        }
    return {
        "status": "degraded",
        "error": "Blob service not configured",
        "service": "storage_tiering",
    }


@router.get("/media/{media_id}/tier")
async def get_media_tier(
    media_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get current storage tier for a video.

    Returns tier info including:
    - Current tier (Hot, Cool, Cold, Archive)
    - Rehydration status if archived
    - Estimated rehydration time
    """
    media = get_media_or_404(media_id, current_user)
    db = get_database_service()

    service = get_storage_tiering_service()
    tier_info = service.get_blob_tier_info(media.blob_name)

    if not tier_info:
        # Return cached info from database if blob not accessible
        return {
            "media_id": media_id,
            "blob_name": media.blob_name,
            "storage_tier": media.storage_tier or "Hot",
            "rehydration_status": media.rehydration_status,
            "last_accessed_at": (
                media.last_accessed_at.isoformat() if media.last_accessed_at else None
            ),
            "source": "database",
        }

    # Update database with current tier from Azure
    if tier_info.current_tier.value != media.storage_tier:
        db.update_media(
            media_id,
            {
                "storage_tier": tier_info.current_tier.value,
                "rehydration_status": tier_info.rehydration_status,
            },
        )

    return {
        "media_id": media_id,
        "blob_name": tier_info.blob_name,
        "storage_tier": tier_info.current_tier.value,
        "is_archived": tier_info.is_archived,
        "is_rehydrating": tier_info.is_rehydrating,
        "rehydration_status": tier_info.rehydration_status,
        "estimated_rehydration_time": tier_info.estimated_rehydration_time,
        "last_accessed_at": (
            tier_info.last_accessed.isoformat() if tier_info.last_accessed else None
        ),
        "source": "azure",
    }


@router.post("/media/{media_id}/tier")
async def change_media_tier(
    media_id: str,
    request: ChangeTierRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Change storage tier for a video.

    Tiers:
    - Hot: Fastest access, highest cost
    - Cool: Slightly slower, 30+ days old
    - Cold: Even slower, 90+ days old
    - Archive: 1-15 hours to access, cheapest

    When moving FROM Archive, specify rehydrate_priority:
    - Standard: 1-15 hours (cheaper)
    - High: < 1 hour (more expensive)
    """
    media = get_media_or_404(media_id, current_user)
    db = get_database_service()

    service = get_storage_tiering_service()
    result = service.set_blob_tier(
        media.blob_name,
        request.target_tier,
        request.rehydrate_priority,
    )

    if result.success:
        # Update database
        update_data = {"storage_tier": request.target_tier.value}
        if result.from_tier == StorageTier.ARCHIVE:
            update_data["rehydration_status"] = (
                f"rehydrate-pending-to-{request.target_tier.value.lower()}"
            )
        else:
            update_data["rehydration_status"] = None

        db.update_media(media_id, update_data)

    return {
        "media_id": media_id,
        "success": result.success,
        "from_tier": result.from_tier.value,
        "to_tier": result.to_tier.value,
        "reason": result.reason,
        "error": result.error,
    }


@router.post("/media/{media_id}/rehydrate")
async def rehydrate_media(
    media_id: str,
    request: RehydrateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Rehydrate an archived video.

    Only needed for videos in Archive tier.

    Priority options:
    - Standard: 1-15 hours (cheaper)
    - High: < 1 hour (more expensive)

    Target tier after rehydration:
    - Hot: Immediate access
    - Cool: Slightly cheaper than Hot
    """
    db = get_database_service()
    media = get_media_or_404(media_id, current_user)

    # Check if actually archived
    if media.storage_tier != "Archive":
        raise HTTPException(
            status_code=400, detail=f"Video is not archived (current tier: {media.storage_tier})"
        )

    service = get_storage_tiering_service()
    result = service.rehydrate_blob(
        media.blob_name,
        request.priority,
        request.target_tier,
    )

    if result.success:
        db.update_media(
            media_id,
            {
                "rehydration_status": f"rehydrate-pending-to-{request.target_tier.value.lower()}",
            },
        )

    estimated_time = "< 1 hour" if request.priority == RehydratePriority.HIGH else "1-15 hours"

    return {
        "media_id": media_id,
        "success": result.success,
        "priority": request.priority.value,
        "target_tier": request.target_tier.value,
        "estimated_time": estimated_time,
        "message": (
            f"Rehydration started. Video will be available in {estimated_time}."
            if result.success
            else result.error
        ),
    }


@router.get("/media/{media_id}/recommendation")
async def get_tier_recommendation(
    media_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get tier recommendation for a video based on access pattern.

    Returns:
    - Recommended tier
    - Reason for recommendation
    - Estimated cost savings
    """
    media = get_media_or_404(media_id, current_user)

    service = get_storage_tiering_service()
    recommendation = service.get_tier_recommendation(
        media.last_accessed_at,
        media.file_size,
    )

    return {
        "media_id": media_id,
        "current_tier": media.storage_tier or "Hot",
        "recommended_tier": (
            recommendation["recommended_tier"].value
            if hasattr(recommendation["recommended_tier"], "value")
            else recommendation["recommended_tier"]
        ),
        "reason": recommendation["reason"],
        "days_since_access": recommendation["days_since_access"],
        "estimated_monthly_cost_usd": recommendation["estimated_monthly_cost_usd"],
        "potential_monthly_savings_usd": recommendation["potential_monthly_savings_usd"],
        "should_change": (media.storage_tier or "Hot")
        != (
            recommendation["recommended_tier"].value
            if hasattr(recommendation["recommended_tier"], "value")
            else recommendation["recommended_tier"]
        ),
    }


@router.get("/cost-analysis")
async def get_cost_analysis(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get storage cost analysis for all user's videos.

    Returns:
    - Current monthly costs
    - Optimized monthly costs
    - Potential savings
    - Tier distribution
    - Top recommendations
    """
    db = get_database_service()
    media_list = db.get_media_by_user(current_user.id, limit=1000)

    if not media_list:
        return {
            "total_media_count": 0,
            "message": "No videos found",
        }

    # Convert to dicts for the service
    media_dicts = [m.to_dict() for m in media_list]

    service = get_storage_tiering_service()
    analysis = service.estimate_storage_costs(media_dicts)

    return analysis


@router.post("/lifecycle-policy")
async def generate_lifecycle_policy(
    request: LifecyclePolicyRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Generate Azure Lifecycle Management Policy JSON.

    This policy can be applied via:
    - Azure Portal: Storage Account > Lifecycle Management
    - Azure CLI: az storage account management-policy create

    The policy automatically moves blobs between tiers based on access time.
    """
    service = get_storage_tiering_service()
    policy = service.generate_lifecycle_policy(
        cool_days=request.cool_days,
        cold_days=request.cold_days,
        archive_days=request.archive_days,
        prefix_filter=request.prefix_filter,
    )

    return {
        "policy": policy,
        "instructions": {
            "azure_portal": "Go to Storage Account > Lifecycle Management > Add Rule > Paste JSON",
            "azure_cli": "az storage account management-policy create --account-name <name> --policy @policy.json",
        },
        "thresholds": {
            "cool_after_days": request.cool_days,
            "cold_after_days": request.cold_days,
            "archive_after_days": request.archive_days,
        },
    }


@router.post("/sync-tiers")
async def sync_all_tiers(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Sync storage tier info from Azure for all user's videos.

    Updates the database with current tier information from Azure.
    Useful after lifecycle policies have run.
    """
    db = get_database_service()
    media_list = db.get_media_by_user(current_user.id, limit=1000)

    if not media_list:
        return {"synced": 0, "message": "No videos found"}

    service = get_storage_tiering_service()
    synced = 0
    errors = 0

    for media in media_list:
        try:
            tier_info = service.get_blob_tier_info(media.blob_name)
            if tier_info:
                db.update_media(
                    media.id,
                    {
                        "storage_tier": tier_info.current_tier.value,
                        "rehydration_status": tier_info.rehydration_status,
                    },
                )
                synced += 1
        except Exception:
            errors += 1

    return {
        "synced": synced,
        "errors": errors,
        "total": len(media_list),
    }


@router.post("/media/{media_id}/access")
async def record_media_access(
    media_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Record that a video was accessed (for tier optimization).

    Call this when a user views/plays a video to update last_accessed_at.
    This affects tier recommendations.
    """
    db = get_database_service()
    get_media_or_404(media_id, current_user)

    db.update_media(
        media_id,
        {
            "last_accessed_at": datetime.now(UTC),
        },
    )

    return {
        "media_id": media_id,
        "last_accessed_at": datetime.now(UTC).isoformat(),
        "message": "Access recorded",
    }
