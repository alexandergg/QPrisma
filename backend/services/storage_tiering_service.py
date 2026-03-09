"""
Storage Tiering Service for QPrisma

Manages Azure Blob Storage access tiers for cost optimization.
Automatically moves videos between Hot, Cool, Cold, and Archive tiers
based on access patterns.

Tiers:
- Hot: Frequently accessed, highest cost (~$0.02/GB/month)
- Cool: Infrequently accessed 30+ days (~$0.01/GB/month)
- Cold: Rarely accessed 90+ days (~$0.004/GB/month)
- Archive: Historical data 180+ days (~$0.001/GB/month) - 1-15h rehydration

Cost Savings:
- Archive tier is ~95% cheaper than Hot tier
- Lifecycle policies handle transitions automatically
"""

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from azure.storage.blob import BlobServiceClient, StandardBlobTier
from pydantic import BaseModel

from core.config import settings

logger = logging.getLogger(__name__)


class StorageTier(str, Enum):
    """Azure Blob Storage access tiers."""

    HOT = "Hot"
    COOL = "Cool"
    COLD = "Cold"
    ARCHIVE = "Archive"


class RehydratePriority(str, Enum):
    """Rehydration priority for archived blobs."""

    STANDARD = "Standard"  # 1-15 hours, cheaper
    HIGH = "High"  # < 1 hour, more expensive


class TierInfo(BaseModel):
    """Information about a blob's storage tier."""

    blob_name: str
    current_tier: StorageTier
    last_accessed: datetime | None
    rehydration_status: str | None = None
    is_archived: bool = False
    is_rehydrating: bool = False
    estimated_rehydration_time: str | None = None


class TierTransition(BaseModel):
    """Represents a tier transition for a blob."""

    blob_name: str
    from_tier: StorageTier
    to_tier: StorageTier
    reason: str
    success: bool
    error: str | None = None


class StorageTieringService:
    """
    Service for managing Azure Blob Storage tiers.

    Provides methods to:
    - Check current tier of blobs
    - Change tier manually
    - Rehydrate archived blobs
    - Generate lifecycle policy JSON
    - Get tier recommendations based on access patterns
    """

    # Default tier transition thresholds (days since last access)
    DEFAULT_COOL_THRESHOLD = 30
    DEFAULT_COLD_THRESHOLD = 90
    DEFAULT_ARCHIVE_THRESHOLD = 180

    def __init__(
        self,
        blob_service: BlobServiceClient | None = None,
        container_name: str | None = None,
    ):
        """
        Initialize Storage Tiering Service.

        Args:
            blob_service: Azure Blob Service Client (uses env var if not provided)
            container_name: Container name for media (uses env var if not provided)
        """
        self.blob_service = blob_service
        self.container_name = container_name or settings.azure.storage_container_name

        if not self.blob_service:
            conn_string = settings.azure.storage_connection_string
            if conn_string:
                self.blob_service = BlobServiceClient.from_connection_string(conn_string)

    def _get_container_client(self):
        """Get the container client."""
        if not self.blob_service:
            raise ValueError("Blob service not configured")
        return self.blob_service.get_container_client(self.container_name)

    def _get_blob_client(self, blob_name: str):
        """Get a blob client for the specified blob."""
        return self._get_container_client().get_blob_client(blob_name)

    def get_blob_tier_info(self, blob_name: str) -> TierInfo | None:
        """
        Get current tier information for a blob.

        Args:
            blob_name: Name of the blob in storage

        Returns:
            TierInfo with current tier and status, or None if blob doesn't exist
        """
        try:
            blob_client = self._get_blob_client(blob_name)
            props = blob_client.get_blob_properties()

            current_tier = StorageTier(props.blob_tier) if props.blob_tier else StorageTier.HOT
            rehydration_status = props.archive_status

            is_archived = current_tier == StorageTier.ARCHIVE
            is_rehydrating = (
                rehydration_status is not None and "rehydrate" in str(rehydration_status).lower()
            )

            # Estimate rehydration time based on priority
            estimated_time = None
            if is_rehydrating:
                if "high" in str(rehydration_status).lower():
                    estimated_time = "< 1 hour"
                else:
                    estimated_time = "1-15 hours"

            return TierInfo(
                blob_name=blob_name,
                current_tier=current_tier,
                last_accessed=props.last_accessed_on,
                rehydration_status=rehydration_status,
                is_archived=is_archived,
                is_rehydrating=is_rehydrating,
                estimated_rehydration_time=estimated_time,
            )
        except Exception as e:
            logger.error(f"Error getting tier info for {blob_name}: {e}")
            return None

    def set_blob_tier(
        self,
        blob_name: str,
        target_tier: StorageTier,
        rehydrate_priority: RehydratePriority = RehydratePriority.STANDARD,
    ) -> TierTransition:
        """
        Change the storage tier for a blob.

        Args:
            blob_name: Name of the blob
            target_tier: Target storage tier
            rehydrate_priority: Priority for rehydration (if moving from Archive)

        Returns:
            TierTransition with result of the operation
        """
        try:
            blob_client = self._get_blob_client(blob_name)
            props = blob_client.get_blob_properties()

            current_tier = StorageTier(props.blob_tier) if props.blob_tier else StorageTier.HOT

            # Map to Azure SDK tier enum
            tier_mapping = {
                StorageTier.HOT: StandardBlobTier.HOT,
                StorageTier.COOL: StandardBlobTier.COOL,
                StorageTier.COLD: StandardBlobTier.COLD,
                StorageTier.ARCHIVE: StandardBlobTier.ARCHIVE,
            }

            azure_tier = tier_mapping[target_tier]

            # Set tier with rehydration priority if coming from Archive
            if current_tier == StorageTier.ARCHIVE and target_tier != StorageTier.ARCHIVE:
                blob_client.set_standard_blob_tier(
                    azure_tier, rehydrate_priority=rehydrate_priority.value
                )
                reason = f"Rehydrating from Archive with {rehydrate_priority.value} priority"
            else:
                blob_client.set_standard_blob_tier(azure_tier)
                reason = "Manual tier change"

            logger.info(f"Changed tier for {blob_name}: {current_tier} → {target_tier}")

            return TierTransition(
                blob_name=blob_name,
                from_tier=current_tier,
                to_tier=target_tier,
                reason=reason,
                success=True,
            )
        except Exception as e:
            logger.error(f"Error changing tier for {blob_name}: {e}")
            return TierTransition(
                blob_name=blob_name,
                from_tier=StorageTier.HOT,
                to_tier=target_tier,
                reason="Error",
                success=False,
                error=str(e),
            )

    def rehydrate_blob(
        self,
        blob_name: str,
        priority: RehydratePriority = RehydratePriority.STANDARD,
        target_tier: StorageTier = StorageTier.HOT,
    ) -> TierTransition:
        """
        Rehydrate an archived blob.

        Args:
            blob_name: Name of the blob
            priority: Rehydration priority (Standard: 1-15h, High: <1h)
            target_tier: Target tier after rehydration (Hot or Cool)

        Returns:
            TierTransition with result
        """
        if target_tier not in [StorageTier.HOT, StorageTier.COOL]:
            return TierTransition(
                blob_name=blob_name,
                from_tier=StorageTier.ARCHIVE,
                to_tier=target_tier,
                reason="Invalid target tier for rehydration",
                success=False,
                error="Target tier must be Hot or Cool",
            )

        return self.set_blob_tier(blob_name, target_tier, priority)

    def get_tier_recommendation(
        self,
        last_accessed: datetime | None,
        file_size_bytes: int | None = None,
    ) -> dict[str, Any]:
        """
        Get tier recommendation based on access pattern.

        Args:
            last_accessed: Last access timestamp
            file_size_bytes: File size for cost estimation

        Returns:
            Dict with recommended tier and estimated savings
        """
        if not last_accessed:
            return {
                "recommended_tier": StorageTier.HOT,
                "reason": "No access data available",
                "days_since_access": None,
                "estimated_monthly_cost": None,
                "potential_savings": None,
            }

        days_since_access = (datetime.now(UTC) - last_accessed).days

        # Determine recommended tier
        if days_since_access >= self.DEFAULT_ARCHIVE_THRESHOLD:
            recommended = StorageTier.ARCHIVE
            reason = f"Not accessed in {days_since_access} days (>180)"
        elif days_since_access >= self.DEFAULT_COLD_THRESHOLD:
            recommended = StorageTier.COLD
            reason = f"Not accessed in {days_since_access} days (>90)"
        elif days_since_access >= self.DEFAULT_COOL_THRESHOLD:
            recommended = StorageTier.COOL
            reason = f"Not accessed in {days_since_access} days (>30)"
        else:
            recommended = StorageTier.HOT
            reason = f"Accessed within last {days_since_access} days"

        # Cost estimation (per GB/month in USD)
        tier_costs = {
            StorageTier.HOT: 0.0208,
            StorageTier.COOL: 0.0115,
            StorageTier.COLD: 0.0036,
            StorageTier.ARCHIVE: 0.00099,
        }

        estimated_cost = None
        potential_savings = None

        if file_size_bytes:
            size_gb = file_size_bytes / (1024 * 1024 * 1024)
            hot_cost = size_gb * tier_costs[StorageTier.HOT]
            recommended_cost = size_gb * tier_costs[recommended]
            estimated_cost = round(recommended_cost, 4)
            potential_savings = (
                round(hot_cost - recommended_cost, 4) if recommended != StorageTier.HOT else 0
            )

        return {
            "recommended_tier": recommended,
            "reason": reason,
            "days_since_access": days_since_access,
            "estimated_monthly_cost_usd": estimated_cost,
            "potential_monthly_savings_usd": potential_savings,
        }

    def generate_lifecycle_policy(
        self,
        cool_days: int = DEFAULT_COOL_THRESHOLD,
        cold_days: int = DEFAULT_COLD_THRESHOLD,
        archive_days: int = DEFAULT_ARCHIVE_THRESHOLD,
        prefix_filter: str = "videos/",
    ) -> dict[str, Any]:
        """
        Generate Azure Lifecycle Management Policy JSON.

        This can be applied via Azure Portal or CLI to automate tier transitions.

        Args:
            cool_days: Days until move to Cool tier
            cold_days: Days until move to Cold tier
            archive_days: Days until move to Archive tier
            prefix_filter: Blob prefix to apply policy to

        Returns:
            Lifecycle policy JSON for Azure
        """
        return {
            "rules": [
                {
                    "enabled": True,
                    "name": "qprisma-tiering-policy",
                    "type": "Lifecycle",
                    "definition": {
                        "actions": {
                            "baseBlob": {
                                "tierToCool": {"daysAfterLastAccessTimeGreaterThan": cool_days},
                                "tierToCold": {"daysAfterLastAccessTimeGreaterThan": cold_days},
                                "tierToArchive": {
                                    "daysAfterLastAccessTimeGreaterThan": archive_days
                                },
                            }
                        },
                        "filters": {
                            "blobTypes": ["blockBlob"],
                            "prefixMatch": [prefix_filter] if prefix_filter else [],
                        },
                    },
                }
            ]
        }

    def estimate_storage_costs(
        self,
        media_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Estimate storage costs and potential savings for a list of media items.

        Args:
            media_items: List of dicts with 'file_size', 'last_accessed_at', 'storage_tier'

        Returns:
            Cost analysis with current costs and potential savings
        """
        tier_costs = {
            "Hot": 0.0208,
            "Cool": 0.0115,
            "Cold": 0.0036,
            "Archive": 0.00099,
        }

        total_size_bytes = 0
        current_monthly_cost = 0.0
        optimized_monthly_cost = 0.0
        tier_distribution = {"Hot": 0, "Cool": 0, "Cold": 0, "Archive": 0}
        recommendations = []

        for item in media_items:
            file_size = item.get("file_size", 0) or 0
            last_accessed = item.get("last_accessed_at")
            current_tier = item.get("storage_tier", "Hot")

            if isinstance(last_accessed, str):
                last_accessed = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))

            total_size_bytes += file_size
            size_gb = file_size / (1024 * 1024 * 1024)

            # Current cost
            current_monthly_cost += size_gb * tier_costs.get(current_tier, tier_costs["Hot"])
            tier_distribution[current_tier] = tier_distribution.get(current_tier, 0) + 1

            # Get recommendation
            rec = self.get_tier_recommendation(last_accessed, file_size)
            recommended_tier = (
                rec["recommended_tier"].value
                if isinstance(rec["recommended_tier"], StorageTier)
                else rec["recommended_tier"]
            )
            optimized_monthly_cost += size_gb * tier_costs.get(recommended_tier, tier_costs["Hot"])

            if recommended_tier != current_tier:
                recommendations.append(
                    {
                        "media_id": item.get("id"),
                        "blob_name": item.get("blob_name"),
                        "current_tier": current_tier,
                        "recommended_tier": recommended_tier,
                        "reason": rec["reason"],
                        "monthly_savings_usd": rec.get("potential_monthly_savings_usd", 0),
                    }
                )

        return {
            "total_media_count": len(media_items),
            "total_size_gb": round(total_size_bytes / (1024 * 1024 * 1024), 2),
            "tier_distribution": tier_distribution,
            "current_monthly_cost_usd": round(current_monthly_cost, 4),
            "optimized_monthly_cost_usd": round(optimized_monthly_cost, 4),
            "potential_monthly_savings_usd": round(
                current_monthly_cost - optimized_monthly_cost, 4
            ),
            "savings_percentage": round(
                (
                    ((current_monthly_cost - optimized_monthly_cost) / current_monthly_cost * 100)
                    if current_monthly_cost > 0
                    else 0
                ),
                1,
            ),
            "recommendations_count": len(recommendations),
            "recommendations": recommendations[:20],  # Top 20 recommendations
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_storage_tiering_service: StorageTieringService | None = None


def get_storage_tiering_service() -> StorageTieringService:
    """Get or create Storage Tiering Service singleton."""
    global _storage_tiering_service
    if _storage_tiering_service is None:
        _storage_tiering_service = StorageTieringService()
    return _storage_tiering_service
