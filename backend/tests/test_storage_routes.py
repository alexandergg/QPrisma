"""Tests for storage tiering routes."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.storage_tiering_service import (
    RehydratePriority,
    StorageTier,
    TierInfo,
    TierTransition,
)


def _media(
    *,
    media_id: str = "media-1",
    user_id: str = "user_test123",
    blob_name: str = "videos/media-1.mp4",
    storage_tier: str | None = "Hot",
):
    media = MagicMock()
    media.id = media_id
    media.user_id = user_id
    media.blob_name = blob_name
    media.storage_tier = storage_tier
    media.rehydration_status = None
    media.last_accessed_at = datetime.now(UTC) - timedelta(days=45)
    media.file_size = 1024 * 1024 * 100
    media.to_dict.return_value = {
        "id": media_id,
        "user_id": user_id,
        "storage_tier": storage_tier or "Hot",
        "file_size": media.file_size,
        "last_accessed_at": media.last_accessed_at,
    }
    return media


@pytest.fixture
def admin_client(app, superuser):
    """TestClient authenticated as a superuser."""
    from api.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: superuser
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def storage_service():
    """Mock StorageTieringService used by route tests."""
    service = MagicMock()
    service.blob_service = MagicMock()
    service.container_name = "media"
    service.get_blob_tier_info.return_value = TierInfo(
        blob_name="videos/media-1.mp4",
        current_tier=StorageTier.COOL,
        last_accessed=datetime(2024, 1, 1, tzinfo=UTC),
        rehydration_status=None,
        is_archived=False,
        is_rehydrating=False,
        estimated_rehydration_time=None,
    )
    service.set_blob_tier.return_value = TierTransition(
        blob_name="videos/media-1.mp4",
        from_tier=StorageTier.HOT,
        to_tier=StorageTier.COOL,
        reason="Manual tier change",
        success=True,
    )
    service.rehydrate_blob.return_value = TierTransition(
        blob_name="videos/media-1.mp4",
        from_tier=StorageTier.ARCHIVE,
        to_tier=StorageTier.HOT,
        reason="Rehydrating from Archive",
        success=True,
    )
    service.get_tier_recommendation.return_value = {
        "recommended_tier": StorageTier.COOL,
        "reason": "Not accessed recently",
        "days_since_access": 45,
        "estimated_monthly_cost_usd": 0.12,
        "potential_monthly_savings_usd": 0.08,
    }
    service.estimate_storage_costs.return_value = {
        "total_media_count": 1,
        "current_monthly_cost_usd": 0.2,
        "optimized_monthly_cost_usd": 0.12,
    }
    service.generate_lifecycle_policy.return_value = {
        "rules": [{"name": "qprisma-tiering-policy", "enabled": True}]
    }
    return service


@pytest.fixture
def route_dependencies(storage_service):
    """Patch direct service/database lookups used by storage routes."""
    db = MagicMock()
    db.get_media.return_value = _media()
    db.get_media_by_user.return_value = [_media()]

    with (
        patch("api.dependencies.get_database_service", return_value=db),
        patch("api.routes.storage_routes.get_database_service", return_value=db),
        patch(
            "api.routes.storage_routes.get_storage_tiering_service",
            return_value=storage_service,
        ),
    ):
        yield db


@pytest.mark.unit
class TestStorageHealthEndpoint:
    def test_health_success_when_blob_service_configured(self, client, storage_service):
        with patch(
            "api.routes.storage_routes.get_storage_tiering_service",
            return_value=storage_service,
        ):
            response = client.get("/storage/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "healthy",
            "container": "media",
            "service": "storage_tiering",
        }

    def test_health_degraded_when_blob_service_not_configured(self, client, storage_service):
        storage_service.blob_service = None
        with patch(
            "api.routes.storage_routes.get_storage_tiering_service",
            return_value=storage_service,
        ):
            response = client.get("/storage/health")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"


@pytest.mark.unit
class TestGetMediaTierEndpoint:
    def test_get_tier_requires_auth(self, client):
        response = client.get("/storage/media/media-1/tier")
        assert response.status_code in (401, 403)

    def test_get_tier_returns_azure_tier_and_updates_database(
        self, authenticated_client, route_dependencies, storage_service
    ):
        response = authenticated_client.get("/storage/media/media-1/tier")

        assert response.status_code == 200
        body = response.json()
        assert body["storage_tier"] == "Cool"
        assert body["source"] == "azure"
        storage_service.get_blob_tier_info.assert_called_once_with("videos/media-1.mp4")
        route_dependencies.update_media.assert_called_once_with(
            "media-1",
            {"storage_tier": "Cool", "rehydration_status": None},
        )

    def test_get_tier_falls_back_to_database(
        self, authenticated_client, route_dependencies, storage_service
    ):
        storage_service.get_blob_tier_info.return_value = None

        response = authenticated_client.get("/storage/media/media-1/tier")

        assert response.status_code == 200
        body = response.json()
        assert body["storage_tier"] == "Hot"
        assert body["source"] == "database"
        route_dependencies.update_media.assert_not_called()

    def test_get_tier_returns_404_for_missing_media(self, authenticated_client, route_dependencies):
        route_dependencies.get_media.return_value = None

        response = authenticated_client.get("/storage/media/missing/tier")

        assert response.status_code == 404

    def test_get_tier_forbids_cross_user_media(self, authenticated_client, route_dependencies):
        route_dependencies.get_media.return_value = _media(user_id="other-user")

        response = authenticated_client.get("/storage/media/media-1/tier")

        assert response.status_code == 403


@pytest.mark.unit
class TestChangeMediaTierEndpoint:
    def test_change_tier_requires_auth(self, client):
        response = client.post("/storage/media/media-1/tier", json={"target_tier": "Cool"})
        assert response.status_code in (401, 403)

    def test_change_tier_updates_database(
        self, authenticated_client, route_dependencies, storage_service
    ):
        response = authenticated_client.post(
            "/storage/media/media-1/tier",
            json={"target_tier": "Cool", "rehydrate_priority": "Standard"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["to_tier"] == "Cool"
        storage_service.set_blob_tier.assert_called_once_with(
            "videos/media-1.mp4",
            StorageTier.COOL,
            RehydratePriority.STANDARD,
        )
        route_dependencies.update_media.assert_called_once_with(
            "media-1",
            {"storage_tier": "Cool", "rehydration_status": None},
        )


@pytest.mark.unit
class TestRehydrateMediaEndpoint:
    def test_rehydrate_requires_auth(self, client):
        response = client.post(
            "/storage/media/media-1/rehydrate",
            json={"priority": "Standard", "target_tier": "Hot"},
        )
        assert response.status_code in (401, 403)

    def test_rehydrate_rejects_non_archive_media(self, authenticated_client, route_dependencies):
        route_dependencies.get_media.return_value = _media(storage_tier="Cool")

        response = authenticated_client.post(
            "/storage/media/media-1/rehydrate",
            json={"priority": "Standard", "target_tier": "Hot"},
        )

        assert response.status_code == 400

    def test_rehydrate_archive_media_updates_status(
        self, authenticated_client, route_dependencies, storage_service
    ):
        route_dependencies.get_media.return_value = _media(storage_tier="Archive")

        response = authenticated_client.post(
            "/storage/media/media-1/rehydrate",
            json={"priority": "High", "target_tier": "Hot"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["estimated_time"] == "< 1 hour"
        storage_service.rehydrate_blob.assert_called_once_with(
            "videos/media-1.mp4",
            RehydratePriority.HIGH,
            StorageTier.HOT,
        )
        route_dependencies.update_media.assert_called_once_with(
            "media-1",
            {"rehydration_status": "rehydrate-pending-to-hot"},
        )


@pytest.mark.unit
class TestTierRecommendationEndpoint:
    def test_get_recommendation_requires_auth(self, client):
        response = client.get("/storage/media/media-1/recommendation")
        assert response.status_code in (401, 403)

    def test_get_recommendation_returns_service_result(
        self, authenticated_client, route_dependencies, storage_service
    ):
        response = authenticated_client.get("/storage/media/media-1/recommendation")

        assert response.status_code == 200
        body = response.json()
        assert body["current_tier"] == "Hot"
        assert body["recommended_tier"] == "Cool"
        assert body["should_change"] is True
        storage_service.get_tier_recommendation.assert_called_once()


@pytest.mark.unit
class TestCostAnalysisEndpoint:
    def test_cost_analysis_requires_auth(self, client):
        response = client.get("/storage/cost-analysis")
        assert response.status_code in (401, 403)

    def test_cost_analysis_uses_current_users_media(
        self, authenticated_client, route_dependencies, storage_service
    ):
        response = authenticated_client.get("/storage/cost-analysis")

        assert response.status_code == 200
        assert response.json()["total_media_count"] == 1
        route_dependencies.get_media_by_user.assert_called_once_with("user_test123", limit=1000)
        storage_service.estimate_storage_costs.assert_called_once()


@pytest.mark.unit
class TestLifecyclePolicyEndpoint:
    def test_lifecycle_policy_requires_auth(self, client):
        response = client.post("/storage/lifecycle-policy", json={})
        assert response.status_code in (401, 403)

    def test_lifecycle_policy_forbids_non_superuser(self, authenticated_client, route_dependencies):
        response = authenticated_client.post("/storage/lifecycle-policy", json={})
        assert response.status_code == 403

    def test_lifecycle_policy_superuser_succeeds(
        self, admin_client, route_dependencies, storage_service
    ):
        response = admin_client.post(
            "/storage/lifecycle-policy",
            json={
                "cool_days": 30,
                "cold_days": 90,
                "archive_days": 180,
                "prefix_filter": "videos/",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["policy"]["rules"][0]["name"] == "qprisma-tiering-policy"
        storage_service.generate_lifecycle_policy.assert_called_once_with(
            cool_days=30,
            cold_days=90,
            archive_days=180,
            prefix_filter="videos/",
        )
