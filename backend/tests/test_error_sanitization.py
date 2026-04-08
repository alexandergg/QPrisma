"""
Tests for error message sanitization across API routes.

Verifies that internal exception details are NOT leaked to clients
and that generic, safe error messages are returned instead.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.batch_processor import BatchProcessor

# =============================================================================
# Processing Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestProcessingRoutesErrorSanitization:
    """Verify processing route 500s never expose internal details."""

    def test_ffmpeg_process_hides_error_details(self, authenticated_client):
        mock_processor = MagicMock()
        mock_db = MagicMock()
        mock_media = MagicMock()
        mock_media.media_type = "video"
        mock_media.blob_name = "test.mp4"
        mock_db.get_media.return_value = mock_media

        with (
            patch("api.routes.processing_routes.get_video_processor", return_value=mock_processor),
            patch("api.routes.processing_routes.get_database_service", return_value=mock_db),
            patch(
                "fastapi.BackgroundTasks.add_task",
                side_effect=RuntimeError("secret DB connection string leaked"),
            ),
        ):
            resp = authenticated_client.post("/process/video/ffmpeg?media_id=m1&preset=balanced")

        assert resp.status_code == 500
        body = resp.json()
        assert "secret" not in body.get("detail", "")
        assert "leaked" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_batch_status_hides_error_details(self, authenticated_client):
        mock_processor = MagicMock()

        with (
            patch("api.routes.processing_routes.get_video_processor", return_value=mock_processor),
            patch(
                "services.batch_processor.BatchProcessor.check_batch_status",
                side_effect=RuntimeError("Azure SDK internal error with key=abc123"),
            ),
        ):
            resp = authenticated_client.get("/batch/status?batch_id=bid_1")

        assert resp.status_code == 500
        body = resp.json()
        assert "Azure SDK" not in body.get("detail", "")
        assert "abc123" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_batch_cancel_hides_error_details(self, authenticated_client):
        mock_processor = MagicMock()

        with (
            patch("api.routes.processing_routes.get_video_processor", return_value=mock_processor),
            patch.object(
                BatchProcessor,
                "cancel_batch",
                new=AsyncMock(side_effect=RuntimeError("internal cancel error")),
            ),
        ):
            resp = authenticated_client.post("/batch/cancel?batch_id=bid_1")

        assert resp.status_code == 500
        body = resp.json()
        assert "internal cancel" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_pipeline_preview_hides_error_details(self, authenticated_client):
        mock_processor = MagicMock()
        mock_processor.get_processing_pipeline_preview.side_effect = RuntimeError(
            "ffmpeg binary not found at /usr/local/bin/ffmpeg"
        )

        with patch("api.routes.processing_routes.get_video_processor", return_value=mock_processor):
            resp = authenticated_client.get("/pipeline/preview")

        assert resp.status_code == 500
        body = resp.json()
        assert "/usr/local/bin/ffmpeg" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_search_hides_error_details(self, authenticated_client):
        with patch(
            "api.routes.chat_routes.get_graph_search_service",
            side_effect=RuntimeError("Neo4j connection refused at bolt://localhost:7687"),
        ):
            resp = authenticated_client.post(
                "/search",
                json={"query": "test"},
            )

        assert resp.status_code == 500
        body_str = str(resp.json())
        assert "Neo4j" not in body_str
        assert "bolt://" not in body_str


# =============================================================================
# Batch Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestBatchRoutesErrorSanitization:
    """Verify batch route 500s never expose internal details."""

    def test_batch_status_hides_error(self, authenticated_client):
        mock_processor = MagicMock()
        mock_db = MagicMock()
        mock_db.get_batch_job_by_azure_id.side_effect = RuntimeError("PG connection pool error")

        with (
            patch("api.routes.batch_routes.get_video_processor", return_value=mock_processor),
            patch("api.routes.batch_routes.get_database_service", return_value=mock_db),
            patch(
                "services.batch_processor.BatchProcessor.check_batch_status",
                return_value={
                    "status": "completed",
                    "request_counts": {"total": 10, "completed": 10, "failed": 0},
                },
            ),
        ):
            resp = authenticated_client.get("/batch/status/azure_batch_123")

        assert resp.status_code == 500
        body = resp.json()
        assert "PG connection" not in body.get("detail", "")
        assert body["detail"] == "Batch operation failed"

    def test_list_jobs_hides_error(self, authenticated_client):
        mock_db = MagicMock()
        mock_db.get_batch_jobs_by_user.side_effect = RuntimeError("SQL syntax error")

        with patch("api.routes.batch_routes.get_database_service", return_value=mock_db):
            resp = authenticated_client.get("/batch/jobs")

        assert resp.status_code == 500
        body = resp.json()
        assert "SQL" not in body.get("detail", "")
        assert body["detail"] == "Batch operation failed"

    def test_cost_summary_hides_error(self, authenticated_client):
        mock_db = MagicMock()
        mock_db.get_batch_cost_summary.side_effect = RuntimeError("table not found")

        with patch("api.routes.batch_routes.get_database_service", return_value=mock_db):
            resp = authenticated_client.get("/batch/cost-summary")

        assert resp.status_code == 500
        body = resp.json()
        assert "table not found" not in body.get("detail", "")
        assert body["detail"] == "Batch operation failed"


# =============================================================================
# Cache Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestCacheRoutesErrorSanitization:
    """Verify cache invalidation 500 never exposes internal details."""

    def test_invalidate_hides_error(self, authenticated_client, app):
        from api.routes.cache_routes import get_cache

        mock_cache = AsyncMock()
        mock_cache.clear_all = AsyncMock(
            side_effect=ConnectionError("Redis AUTH failed: invalid password")
        )
        app.dependency_overrides[get_cache] = lambda: mock_cache

        resp = authenticated_client.post("/cache/invalidate", json={"clear_all": True})

        assert resp.status_code == 500
        body = resp.json()
        assert "Redis AUTH" not in body.get("detail", "")
        assert "password" not in body.get("detail", "")
        assert body["detail"] == "Cache operation failed"

        app.dependency_overrides.pop(get_cache, None)


# =============================================================================
# Jobs Routes — error sanitization
# =============================================================================


@pytest.mark.unit
class TestJobsRoutesErrorSanitization:
    """Verify jobs route 500s never expose internal details."""

    def test_submit_job_hides_error(self, authenticated_client):
        mock_celery = MagicMock()

        with (
            patch("api.routes.jobs_routes.get_celery_app", return_value=mock_celery),
            patch(
                "tasks.video_tasks.process_video_pipeline",
                create=True,
            ) as mock_task,
        ):
            mock_task.apply_async.side_effect = RuntimeError(
                "Celery broker amqp://user:pass@host unreachable"
            )
            resp = authenticated_client.post(
                "/jobs/submit",
                json={"video_id": "v1", "blob_name": "v1.mp4"},
            )

        assert resp.status_code == 500
        body = resp.json()
        assert "amqp://" not in body.get("detail", "")
        assert "pass" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_get_job_status_hides_error(self, authenticated_client):
        mock_celery = MagicMock()

        with (
            patch("api.routes.jobs_routes.get_celery_app", return_value=mock_celery),
            patch(
                "celery.result.AsyncResult",
                side_effect=RuntimeError("Celery backend connection error"),
                create=True,
            ),
        ):
            resp = authenticated_client.get("/jobs/job_123")

        assert resp.status_code == 500
        body = resp.json()
        assert "backend connection" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_cancel_job_hides_error(self, authenticated_client):
        mock_celery = MagicMock()

        with (
            patch("api.routes.jobs_routes.get_celery_app", return_value=mock_celery),
            patch(
                "celery.result.AsyncResult",
                side_effect=RuntimeError("internal error"),
                create=True,
            ),
        ):
            resp = authenticated_client.post("/jobs/job_123/cancel")

        assert resp.status_code == 500
        body = resp.json()
        assert "internal error" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"

    def test_get_result_hides_error(self, authenticated_client):
        mock_celery = MagicMock()

        with (
            patch("api.routes.jobs_routes.get_celery_app", return_value=mock_celery),
            patch(
                "celery.result.AsyncResult",
                side_effect=RuntimeError("backend unavailable"),
                create=True,
            ),
        ):
            resp = authenticated_client.get("/jobs/job_123/result")

        assert resp.status_code == 500
        body = resp.json()
        assert "backend unavailable" not in body.get("detail", "")
        assert body["detail"] == "Processing operation failed"


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
                    "block_ids": ["block1"],
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
