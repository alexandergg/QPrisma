"""
Tests for error message sanitization across API routes.

Verifies that internal exception details are NOT leaked to clients
and that generic, safe error messages are returned instead.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Processing Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestProcessingRoutesErrorSanitization:
    """Verify processing route 500s never expose internal details."""

    def test_ffmpeg_endpoint_removed(self, authenticated_client):
        """POST /process/video/ffmpeg was removed — verify 404/405."""
        resp = authenticated_client.post("/process/video/ffmpeg?media_id=m1&preset=balanced")
        assert resp.status_code in (404, 405)

    def test_pipeline_preview_removed(self, authenticated_client):
        resp = authenticated_client.get("/pipeline/preview")
        assert resp.status_code == 404

    def test_search_endpoint_removed(self, authenticated_client):
        """POST /search was removed — verify 404/405."""
        resp = authenticated_client.post("/search", json={"query": "test"})
        assert resp.status_code in (404, 405)


# =============================================================================
# Batch Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestBatchRoutesRemoved:
    """Verify legacy batch routes are no longer mounted."""

    def test_batch_routes_removed(self, authenticated_client):
        resp = authenticated_client.get("/batch/status/azure_batch_123")
        assert resp.status_code == 404


# =============================================================================
# Cache Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestCacheRoutesErrorSanitization:
    """Verify cache invalidation 500 never exposes internal details."""

    def test_invalidate_hides_error(self, authenticated_client, app, superuser):
        from api.dependencies import get_current_user
        from api.routes.cache_routes import get_cache

        mock_cache = AsyncMock()
        mock_cache.clear_all = AsyncMock(
            side_effect=ConnectionError("Cache backend auth failed: invalid password")
        )
        app.dependency_overrides[get_current_user] = lambda: superuser
        app.dependency_overrides[get_cache] = lambda: mock_cache

        resp = authenticated_client.post("/cache/invalidate", json={"clear_all": True})

        assert resp.status_code == 500
        body = resp.json()
        assert "Cache backend auth" not in body.get("detail", "")
        assert "password" not in body.get("detail", "")
        assert body["detail"] == "Cache operation failed"

        app.dependency_overrides.pop(get_cache, None)
        app.dependency_overrides.pop(get_current_user, None)


# =============================================================================
# Jobs Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestJobsRoutesErrorSanitization:
    """Verify legacy processing job routes are no longer mounted."""

    def test_submit_endpoint_removed(self, authenticated_client):
        """POST /jobs/submit was removed — verify 404/405."""
        resp = authenticated_client.post(
            "/jobs/submit",
            json={"video_id": "v1", "blob_name": "v1.mp4"},
        )
        assert resp.status_code in (404, 405)

    def test_jobs_routes_removed(self, authenticated_client):
        resp = authenticated_client.get("/jobs/job_123")
        assert resp.status_code == 404


# =============================================================================
# Chunked Upload Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestChunkedUploadErrorSanitization:
    """Verify chunked upload 500s never expose internal details."""

    def test_commit_hides_error(self, authenticated_client):
        mock_db = MagicMock()
        mock_blob = MagicMock()
        mock_media = MagicMock()
        mock_media.user_id = "user_test123"
        mock_db.get_media.return_value = mock_media

        mock_blob_client = MagicMock()
        mock_blob_client.commit_block_list.side_effect = RuntimeError(
            "Azure SharedKey credential invalid"
        )
        mock_blob.get_blob_client.return_value = mock_blob_client

        with (
            patch("api.routes.chunked_upload_routes.get_blob_service", return_value=mock_blob),
            patch("api.routes.chunked_upload_routes.get_database_service", return_value=mock_db),
            patch(
                "api.routes.chunked_upload_routes.get_storage_container_name",
                return_value="test-container",
            ),
        ):
            resp = authenticated_client.post(
                "/upload/chunked/commit",
                json={
                    "upload_id": "u1",
                    "media_id": "m1",
                    "blob_name": "test.mp4",
                    "block_ids": ["YmxvY2sx"],
                },
            )

        assert resp.status_code == 500
        body = resp.json()
        assert "SharedKey" not in body.get("detail", "")
        assert body["detail"] == "Storage operation failed"


# =============================================================================
# Structure Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestStructureRoutesErrorSanitization:
    """Verify structure route 500s never expose internal details."""

    def test_get_structure_hides_error(self, authenticated_client):
        mock_db = MagicMock()
        mock_media = MagicMock()
        mock_media.user_id = "user_test123"
        mock_media.to_dict.side_effect = RuntimeError("pg connection refused")
        mock_db.get_media.return_value = mock_media

        with (
            patch("api.routes.structure_routes.get_database_service", return_value=mock_db),
            patch(
                "api.routes.structure_routes.get_knowledge_graph_service",
                side_effect=ImportError("neo4j not installed"),
                create=True,
            ),
        ):
            resp = authenticated_client.get("/media/m1/structure")

        assert resp.status_code == 500
        body = resp.json()
        assert "pg connection" not in body.get("detail", "")
        assert body["detail"] == "An internal error occurred"
