"""
Tests for api/routes/cache_routes.py

Covers authentication requirements on cache management endpoints
and verifies that the health endpoint remains publicly accessible.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_cache_service():
    """Create a mock CacheService for dependency override."""
    mock = MagicMock()
    mock.get_metrics.return_value = {
        "connected": True,
        "backend": "memory",
        "hits": 10,
        "misses": 2,
        "errors": 0,
        "hit_rate": "83.33%",
        "bytes_saved": 1024,
        "api_calls_saved": 5,
        "estimated_cost_saved": "$0.05",
    }
    mock.reset_metrics.return_value = None
    mock.clear_all = AsyncMock(return_value=True)
    mock.invalidate_video = AsyncMock(return_value=3)
    mock.invalidate_by_pattern = AsyncMock(return_value=2)
    mock.config = MagicMock(key_prefix="qprisma", similarity_threshold=8, max_memory_items=500)
    mock.redis_url = "redis://localhost:6379"
    return mock


@pytest.fixture
def _override_cache(app):
    """Override the cache dependency for all cache route tests."""
    from api.routes.cache_routes import get_cache

    mock = _mock_cache_service()
    app.dependency_overrides[get_cache] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_cache, None)


# =============================================================================
# Authentication requirement tests — unauthenticated requests must be rejected
# =============================================================================


@pytest.mark.unit
class TestCacheMetricsAuth:
    def test_requires_auth(self, client, _override_cache):
        resp = client.get("/cache/metrics")
        assert resp.status_code in (401, 403)

    def test_authenticated_succeeds(self, authenticated_client, _override_cache):
        resp = authenticated_client.get("/cache/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["hits"] == 10


@pytest.mark.unit
class TestCacheMetricsResetAuth:
    def test_requires_auth(self, client, _override_cache):
        resp = client.post("/cache/metrics/reset")
        assert resp.status_code in (401, 403)

    def test_authenticated_succeeds(self, authenticated_client, _override_cache):
        resp = authenticated_client.post("/cache/metrics/reset")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Metrics reset successfully"


@pytest.mark.unit
class TestCacheInvalidateAuth:
    def test_requires_auth(self, client, _override_cache):
        resp = client.post("/cache/invalidate", json={"clear_all": True})
        assert resp.status_code in (401, 403)

    def test_authenticated_clear_all(self, authenticated_client, _override_cache):
        resp = authenticated_client.post("/cache/invalidate", json={"clear_all": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "All cache cleared" in body["message"]


@pytest.mark.unit
class TestCacheInvalidateVideoAuth:
    def test_requires_auth(self, client, _override_cache):
        resp = client.delete("/cache/video/vid_123")
        assert resp.status_code in (401, 403)

    def test_authenticated_succeeds(self, authenticated_client, _override_cache):
        resp = authenticated_client.delete("/cache/video/vid_123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["keys_deleted"] == 3


# =============================================================================
# Health endpoint must remain public (no auth required)
# =============================================================================


@pytest.mark.unit
class TestCacheHealthNoAuth:
    def test_health_no_auth_required(self, client, _override_cache):
        resp = client.get("/cache/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["connected"] is True


# =============================================================================
# Config endpoint — auth required, credentials redacted
# =============================================================================


@pytest.mark.unit
class TestCacheConfigSecurity:
    def test_config_requires_auth(self, client, _override_cache):
        resp = client.get("/cache/config")
        assert resp.status_code in (401, 403)

    def test_config_authenticated_succeeds(self, authenticated_client, _override_cache):
        resp = authenticated_client.get("/cache/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["key_prefix"] == "qprisma"

    def test_config_does_not_expose_redis_url(self, authenticated_client, _override_cache):
        resp = authenticated_client.get("/cache/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "redis_url" not in body
        assert "redis" not in str(body).lower() or "redis" in body.get("key_prefix", "").lower()


# =============================================================================
# Removed endpoints — must return 404/405
# =============================================================================


@pytest.mark.unit
class TestCacheJobEndpointsRemoved:
    """Verify that internal-only job status endpoints are no longer exposed."""

    def test_get_job_status_removed(self, client, _override_cache):
        resp = client.get("/cache/job/test-job-123")
        assert resp.status_code in (404, 405)

    def test_put_job_status_removed(self, client, _override_cache):
        resp = client.put("/cache/job/test-job-123?progress=50&stage=processing")
        assert resp.status_code in (404, 405)
