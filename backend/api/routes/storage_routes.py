"""
Storage Tiering API Routes

Endpoints for managing Azure Blob Storage tiers:
- Check current tier of videos
- Change tier manually
- Rehydrate archived videos
- Get tier recommendations
- Generate lifecycle policy
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import (
    get_current_user,
    get_database_service,
    get_media_or_404,
    get_storage_route_service,
    get_storage_tiering_service,
    require_superuser,
)
from core.exceptions import BadRequestError
from models.upload_schemas import StorageHealthResponse
from models.user import User
from services.storage_tiering_service import (
    RehydratePriority,
    StorageTier,
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


@router.get("/health", response_model=StorageHealthResponse)
async def storage_health() -> StorageHealthResponse:
    """Check storage tiering service health."""
    return StorageHealthResponse(
        **get_storage_route_service().get_health(get_storage_tiering_service())
    )


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
    return get_storage_route_service().get_media_tier(media_id, media, db, service)


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
    return get_storage_route_service().change_media_tier(
        media_id,
        media,
        db,
        service,
        request.target_tier,
        request.rehydrate_priority,
    )


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

    service = get_storage_tiering_service()
    try:
        return get_storage_route_service().rehydrate_media(
            media_id,
            media,
            db,
            service,
            request.priority,
            request.target_tier,
        )
    except BadRequestError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


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
    return get_storage_route_service().get_tier_recommendation(media_id, media, service)


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

    service = get_storage_tiering_service()
    return get_storage_route_service().get_cost_analysis(media_list, service)


@router.post("/lifecycle-policy")
async def generate_lifecycle_policy(
    request: LifecyclePolicyRequest,
    current_user: User = Depends(require_superuser),
) -> dict[str, Any]:
    """
    Generate Azure Lifecycle Management Policy JSON.

    This policy can be applied via:
    - Azure Portal: Storage Account > Lifecycle Management
    - Azure CLI: az storage account management-policy create

    The policy automatically moves blobs between tiers based on access time.
    """
    service = get_storage_tiering_service()
    return get_storage_route_service().generate_lifecycle_policy(
        service,
        cool_days=request.cool_days,
        cold_days=request.cold_days,
        archive_days=request.archive_days,
        prefix_filter=request.prefix_filter,
    )
