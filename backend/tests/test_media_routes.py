"""
Tests for api/routes/media_routes.py

Covers upload, list, get, delete, and status endpoints.
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.unit
class TestUploadMedia:
    def test_requires_auth(self, client):
        resp = client.post("/upload", files={"file": ("test.mp4", b"data", "video/mp4")})
        assert resp.status_code in (401, 403)

    def test_no_blob_service_returns_503(self, authenticated_client):
        with patch("api.routes.media_routes.get_blob_service", return_value=None):
            resp = authenticated_client.post(
                "/upload", files={"file": ("test.mp4", b"data", "video/mp4")}
            )
        assert resp.status_code == 503

    def test_upload_video_success(self, authenticated_client, mock_blob_service, mock_db_service):
        with (
            patch("api.routes.media_routes.get_blob_service", return_value=mock_blob_service),
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_storage_container_name", return_value="media"),
            patch("tasks.video_tasks.process_video_pipeline.apply_async") as mock_apply_async,
        ):
            mock_apply_async.return_value = MagicMock(id="job_test123")
            resp = authenticated_client.post(
                "/upload",
                files={"file": ("test.mp4", BytesIO(b"fake_video_data"), "video/mp4")},
            )

        assert resp.status_code == 200
        assert resp.json()["job_id"] == "job_test123"

    def test_upload_image_success(self, authenticated_client, mock_blob_service, mock_db_service):
        with (
            patch("api.routes.media_routes.get_blob_service", return_value=mock_blob_service),
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_storage_container_name", return_value="media"),
        ):
            resp = authenticated_client.post(
                "/upload",
                files={"file": ("photo.jpg", BytesIO(b"fake_img"), "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["media_type"] == "image"


@pytest.mark.unit
class TestListMedia:
    def test_requires_auth(self, client):
        resp = client.get("/media")
        assert resp.status_code in (401, 403)

    def test_list_empty(self, authenticated_client, mock_db_service):
        mock_db_service.get_media_by_user.return_value = []
        with patch("api.routes.media_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/media")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["media"] == []

    def test_list_with_pagination(self, authenticated_client, mock_db_service):
        mock_db_service.get_media_by_user.return_value = []
        with patch("api.routes.media_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/media?limit=10&offset=5")

        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 10
        assert body["offset"] == 5


@pytest.mark.unit
class TestGetMedia:
    def test_requires_auth(self, client):
        resp = client.get("/media/some_id")
        assert resp.status_code in (401, 403)

    def test_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_media.return_value = None
        with patch("api.routes.media_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/media/nonexistent")

        assert resp.status_code == 404

    def test_forbidden(self, authenticated_client, mock_db_service, test_user):
        mock_media = MagicMock()
        mock_media.user_id = "other_user"
        mock_db_service.get_media.return_value = mock_media

        with patch("api.routes.media_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/media/some_id")

        assert resp.status_code == 403

    def test_success(self, authenticated_client, mock_db_service, test_user):
        mock_media = MagicMock()
        mock_media.user_id = test_user.id
        mock_media.to_dict.return_value = {
            "id": "media_123",
            "user_id": test_user.id,
            "blob_name": "test.mp4",
            "media_type": "video",
            "video_metadata": None,
        }
        mock_db_service.get_media.return_value = mock_media

        with (
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_blob_service", return_value=None),
        ):
            resp = authenticated_client.get("/media/media_123")

        assert resp.status_code == 200

    def test_success_includes_signed_blob_url(
        self,
        authenticated_client,
        mock_db_service,
        test_user,
    ):
        item = {
            "id": "media_123",
            "user_id": test_user.id,
            "blob_name": "test.mp4",
            "media_type": "video",
            "video_metadata": {},
        }
        mock_media = MagicMock()
        mock_media.user_id = test_user.id
        mock_media.to_dict.return_value = item
        mock_db_service.get_media.return_value = mock_media

        with (
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch(
                "api.routes.media_routes.hydrate_data_from_blob",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "api.routes.media_routes.build_blob_sas_url_async",
                new=AsyncMock(
                    return_value="https://storage.blob.core.windows.net/media/test.mp4?sig=1"
                ),
            ),
        ):
            resp = authenticated_client.get("/media/media_123")

        assert resp.status_code == 200
        assert (
            resp.json()["blob_url"] == "https://storage.blob.core.windows.net/media/test.mp4?sig=1"
        )


@pytest.mark.unit
class TestDeleteMedia:
    def test_requires_auth(self, client):
        resp = client.delete("/media/some_id")
        assert resp.status_code in (401, 403)

    def test_not_found(self, authenticated_client, mock_db_service, mock_blob_service):
        mock_db_service.get_media.return_value = None
        with (
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_blob_service", return_value=mock_blob_service),
            patch("api.routes.media_routes.get_video_processor", return_value=None),
        ):
            resp = authenticated_client.delete("/media/nonexistent")

        assert resp.status_code == 404

    def test_forbidden(self, authenticated_client, mock_db_service, mock_blob_service):
        mock_media = MagicMock()
        mock_media.user_id = "other_user"
        mock_db_service.get_media.return_value = mock_media

        with (
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_blob_service", return_value=mock_blob_service),
            patch("api.routes.media_routes.get_video_processor", return_value=None),
        ):
            resp = authenticated_client.delete("/media/some_id")

        assert resp.status_code == 403

    def test_success(self, authenticated_client, mock_db_service, mock_blob_service, test_user):
        mock_media = MagicMock()
        mock_media.user_id = test_user.id
        mock_media.blob_name = "test.mp4"
        mock_db_service.get_media.return_value = mock_media

        with (
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
            patch("api.routes.media_routes.get_blob_service", return_value=mock_blob_service),
            patch("api.routes.media_routes.get_video_processor", return_value=None),
            patch("services.knowledge_graph.KnowledgeGraphService") as mock_kg_cls,
        ):
            mock_kg = MagicMock()
            mock_kg.delete_video_subgraph.return_value = True
            mock_kg_cls.return_value = mock_kg
            resp = authenticated_client.delete("/media/some_id")

        assert resp.status_code == 200


@pytest.mark.unit
class TestMediaStatus:
    def test_not_found(self, authenticated_client, mock_db_service):
        with patch(
            "api.routes.media_routes.get_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Media not found"),
        ):
            resp = authenticated_client.get("/media/nonexistent/status")

        assert resp.status_code == 404

    def test_success(self, authenticated_client, mock_db_service):
        mock_db_service.get_media_status.return_value = {
            "status": "completed",
            "progress": 100,
        }
        mock_media = MagicMock(user_id="user_test123")
        with (
            patch("api.routes.media_routes.get_media_or_404", return_value=mock_media),
            patch("api.routes.media_routes.get_database_service", return_value=mock_db_service),
        ):
            resp = authenticated_client.get("/media/some_id/status")

        assert resp.status_code == 200
