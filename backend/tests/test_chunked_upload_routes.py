from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.unit
class TestInitChunkedUpload:
    def test_init_returns_signed_upload_url(
        self,
        authenticated_client,
        mock_blob_service,
        mock_db_service,
    ):
        with (
            patch(
                "api.routes.chunked_upload_routes.get_blob_service", return_value=mock_blob_service
            ),
            patch(
                "api.routes.chunked_upload_routes.get_database_service",
                return_value=mock_db_service,
            ),
            patch(
                "api.routes.chunked_upload_routes.build_blob_sas_url_async",
                new=AsyncMock(
                    return_value="https://storage.blob.core.windows.net/media/upload.mp4?sig=1"
                ),
            ),
        ):
            resp = authenticated_client.post(
                "/upload/chunked/init",
                json={
                    "filename": "upload.mp4",
                    "file_size": 1024,
                    "content_type": "video/mp4",
                    "block_size_mb": 8,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["upload_url"] == "https://storage.blob.core.windows.net/media/upload.mp4?sig=1"
        assert body["blob_name"].endswith(".mp4")
        assert body["total_blocks"] == 1
        assert len(body["blocks"]) == 1
