"""Service-layer orchestration for storage tiering routes."""

from __future__ import annotations

from typing import Any

from core.exceptions import BadRequestError
from services.storage_tiering_service import RehydratePriority, StorageTier


class StorageRouteService:
    """Coordinate storage tiering operations without FastAPI dependencies."""

    def get_health(self, storage_service: Any) -> dict[str, Any]:
        if storage_service.blob_service:
            return {
                "status": "healthy",
                "container": storage_service.container_name,
                "service": "storage_tiering",
            }
        return {
            "status": "degraded",
            "error": "Blob service not configured",
            "service": "storage_tiering",
        }

    def get_media_tier(
        self, media_id: str, media: Any, db: Any, storage_service: Any
    ) -> dict[str, Any]:
        tier_info = storage_service.get_blob_tier_info(media.blob_name)

        if not tier_info:
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

    def change_media_tier(
        self,
        media_id: str,
        media: Any,
        db: Any,
        storage_service: Any,
        target_tier: StorageTier,
        rehydrate_priority: RehydratePriority,
    ) -> dict[str, Any]:
        result = storage_service.set_blob_tier(media.blob_name, target_tier, rehydrate_priority)

        if result.success:
            update_data = {"storage_tier": target_tier.value}
            if result.from_tier == StorageTier.ARCHIVE:
                update_data["rehydration_status"] = (
                    f"rehydrate-pending-to-{target_tier.value.lower()}"
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

    def rehydrate_media(
        self,
        media_id: str,
        media: Any,
        db: Any,
        storage_service: Any,
        priority: RehydratePriority,
        target_tier: StorageTier,
    ) -> dict[str, Any]:
        if media.storage_tier != "Archive":
            raise BadRequestError(f"Video is not archived (current tier: {media.storage_tier})")

        result = storage_service.rehydrate_blob(media.blob_name, priority, target_tier)

        if result.success:
            db.update_media(
                media_id,
                {
                    "rehydration_status": f"rehydrate-pending-to-{target_tier.value.lower()}",
                },
            )

        estimated_time = "< 1 hour" if priority == RehydratePriority.HIGH else "1-15 hours"

        return {
            "media_id": media_id,
            "success": result.success,
            "priority": priority.value,
            "target_tier": target_tier.value,
            "estimated_time": estimated_time,
            "message": (
                f"Rehydration started. Video will be available in {estimated_time}."
                if result.success
                else result.error
            ),
        }

    def get_tier_recommendation(
        self, media_id: str, media: Any, storage_service: Any
    ) -> dict[str, Any]:
        recommendation = storage_service.get_tier_recommendation(
            media.last_accessed_at, media.file_size
        )
        recommended_tier = recommendation["recommended_tier"]
        recommended_tier_value = (
            recommended_tier.value if hasattr(recommended_tier, "value") else recommended_tier
        )
        current_tier = media.storage_tier or "Hot"

        return {
            "media_id": media_id,
            "current_tier": current_tier,
            "recommended_tier": recommended_tier_value,
            "reason": recommendation["reason"],
            "days_since_access": recommendation["days_since_access"],
            "estimated_monthly_cost_usd": recommendation["estimated_monthly_cost_usd"],
            "potential_monthly_savings_usd": recommendation["potential_monthly_savings_usd"],
            "should_change": current_tier != recommended_tier_value,
        }

    def get_cost_analysis(self, media_list: list[Any], storage_service: Any) -> dict[str, Any]:
        if not media_list:
            return {
                "total_media_count": 0,
                "message": "No videos found",
            }

        return storage_service.estimate_storage_costs([media.to_dict() for media in media_list])

    def generate_lifecycle_policy(
        self,
        storage_service: Any,
        *,
        cool_days: int,
        cold_days: int,
        archive_days: int,
        prefix_filter: str,
    ) -> dict[str, Any]:
        policy = storage_service.generate_lifecycle_policy(
            cool_days=cool_days,
            cold_days=cold_days,
            archive_days=archive_days,
            prefix_filter=prefix_filter,
        )

        return {
            "policy": policy,
            "instructions": {
                "azure_portal": "Go to Storage Account > Lifecycle Management > Add Rule > Paste JSON",
                "azure_cli": "az storage account management-policy create --account-name <name> --policy @policy.json",
            },
            "thresholds": {
                "cool_after_days": cool_days,
                "cold_after_days": cold_days,
                "archive_after_days": archive_days,
            },
        }
