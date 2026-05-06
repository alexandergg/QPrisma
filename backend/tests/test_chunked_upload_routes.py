import base64
import logging
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

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
                "api.routes.chunked_upload_routes.get_blob_service",
                return_value=mock_blob_service,
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


# ---------------------------------------------------------------------------
# Focused unit tests for block ID decoding (no TestClient / full-app needed)
# ---------------------------------------------------------------------------


def _make_media_mock(user_id: str = "user_test123") -> MagicMock:
    """Create a mock media record owned by the given user."""
    media = MagicMock()
    media.user_id = user_id
    return media


def _import_chunked_upload_module():
    """Import chunked_upload_routes directly, bypassing api.routes.__init__.

    Works around a local FastAPI/Starlette version mismatch by patching
    Router.__init__ to accept the deprecated on_startup/on_shutdown kwargs.
    """
    from pathlib import Path

    if "api.routes.chunked_upload_routes" in sys.modules:
        return sys.modules["api.routes.chunked_upload_routes"]

    # Patch Starlette Router to tolerate on_startup/on_shutdown kwargs
    import starlette.routing as _sr

    _orig_init = _sr.Router.__init__

    def _patched_init(self, **kwargs):
        kwargs.pop("on_startup", None)
        kwargs.pop("on_shutdown", None)
        return _orig_init(self, **kwargs)

    _sr.Router.__init__ = _patched_init

    routes_dir = str(Path(__file__).resolve().parent.parent / "api" / "routes")
    stub = types.ModuleType("api.routes")
    stub.__path__ = [routes_dir]
    stub.__package__ = "api.routes"
    sys.modules.setdefault("api.routes", stub)

    import importlib

    mod = importlib.import_module("api.routes.chunked_upload_routes")

    # Restore original
    _sr.Router.__init__ = _orig_init
    return mod


def _build_commit_dependencies(
    user_id: str = "user_test123",
) -> tuple[MagicMock, MagicMock]:
    """Build mock blob_service and db_service for commit tests."""
    blob_service = MagicMock()
    blob_client = MagicMock()
    blob_client.get_blob_properties.return_value = MagicMock(size=4096)
    blob_service.get_blob_client.return_value = blob_client

    db_service = MagicMock()
    db_service.get_media.return_value = _make_media_mock(user_id)

    return blob_service, db_service


def _build_dispatch_service() -> MagicMock:
    dispatch_result = MagicMock()
    dispatch_result.job_id = "job-123"
    dispatch_result.backend = "servicebus"
    dispatch_result.media_updates.return_value = {
        "job_id": "job-123",
        "processing_method": "servicebus",
        "processing_status": "queued",
        "pipeline_config": {"dispatch": {"backend": "servicebus"}},
    }

    dispatch_service = MagicMock()
    dispatch_service.dispatch_video = AsyncMock(return_value=dispatch_result)
    return dispatch_service


def _make_user(user_id: str = "user_test123"):
    from datetime import UTC, datetime

    from models.user import User

    return User(
        id=user_id,
        email="test@example.com",
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.mark.unit
class TestCommitBlockIdDecoding:
    """Tests for block ID base64 decoding during commit."""

    @pytest.mark.asyncio
    async def test_valid_block_ids_are_decoded_before_commit(self):
        """Valid base64 block IDs should be decoded to raw strings for BlobBlock."""
        mod = _import_chunked_upload_module()

        raw_ids = ["block-0001", "block-0002", "block-0003"]
        b64_ids = [base64.b64encode(rid.encode()).decode() for rid in raw_ids]

        blob_service, db_service = _build_commit_dependencies()
        user = _make_user()

        request = mod.CommitUploadRequest(
            upload_id="upload-1",
            media_id="media_123",
            blob_name="videos/test.mp4",
            block_ids=b64_ids,
            use_scene_detection=False,
            use_hierarchical_summary=False,
        )

        with (
            patch.object(mod, "get_blob_service", return_value=blob_service),
            patch.object(mod, "get_database_service", return_value=db_service),
            patch.object(mod, "get_storage_container_name", return_value="media"),
            patch.object(
                mod,
                "get_video_processing_dispatch_service",
                return_value=_build_dispatch_service(),
            ),
        ):
            await mod.commit_chunked_upload(request=request, current_user=user)

        # Verify commit_block_list was called with decoded (raw) block IDs
        blob_client = blob_service.get_blob_client.return_value
        call_args = blob_client.commit_block_list.call_args
        committed_blocks = call_args.kwargs["block_list"]
        committed_ids = [b.id for b in committed_blocks]
        assert committed_ids == raw_ids

    @pytest.mark.asyncio
    async def test_invalid_base64_block_id_returns_400(self):
        """Non-base64 block IDs should be rejected with HTTP 400."""
        from fastapi import HTTPException

        mod = _import_chunked_upload_module()
        blob_service, db_service = _build_commit_dependencies()
        user = _make_user()

        request = mod.CommitUploadRequest(
            upload_id="upload-1",
            media_id="media_123",
            blob_name="videos/test.mp4",
            block_ids=["!!!not-valid-base64!!!"],
            use_scene_detection=False,
            use_hierarchical_summary=False,
        )

        with (
            patch.object(mod, "get_blob_service", return_value=blob_service),
            patch.object(mod, "get_database_service", return_value=db_service),
            patch.object(mod, "get_storage_container_name", return_value="media"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await mod.commit_chunked_upload(request=request, current_user=user)

        assert exc_info.value.status_code == 400
        assert "Invalid base64 block ID" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_bad_padding_block_id_returns_400(self):
        """Base64 with bad padding should be rejected with HTTP 400."""
        from fastapi import HTTPException

        mod = _import_chunked_upload_module()
        blob_service, db_service = _build_commit_dependencies()
        user = _make_user()

        request = mod.CommitUploadRequest(
            upload_id="upload-1",
            media_id="media_123",
            blob_name="videos/test.mp4",
            block_ids=["YWJj="],
            use_scene_detection=False,
            use_hierarchical_summary=False,
        )

        with (
            patch.object(mod, "get_blob_service", return_value=blob_service),
            patch.object(mod, "get_database_service", return_value=db_service),
            patch.object(mod, "get_storage_container_name", return_value="media"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await mod.commit_chunked_upload(request=request, current_user=user)

        assert exc_info.value.status_code == 400
        assert "Invalid base64 block ID" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_commit_uses_configured_dispatch_service(self):
        """Committed uploads should dispatch through the backend abstraction."""
        mod = _import_chunked_upload_module()

        raw_ids = ["block-0001"]
        b64_ids = [base64.b64encode(rid.encode()).decode() for rid in raw_ids]

        blob_service, db_service = _build_commit_dependencies()
        dispatch_service = _build_dispatch_service()
        user = _make_user()

        request = mod.CommitUploadRequest(
            upload_id="upload-1",
            media_id="media_123",
            blob_name="videos/test.mp4",
            block_ids=b64_ids,
            preset="quality",
            max_frames=1000,
            use_scene_detection=True,
            use_hierarchical_summary=True,
        )

        with (
            patch.object(mod, "get_blob_service", return_value=blob_service),
            patch.object(mod, "get_database_service", return_value=db_service),
            patch.object(mod, "get_storage_container_name", return_value="media"),
            patch.object(
                mod,
                "get_video_processing_dispatch_service",
                return_value=dispatch_service,
            ),
        ):
            response = await mod.commit_chunked_upload(request=request, current_user=user)

        dispatch_service.dispatch_video.assert_awaited_once_with(
            media_id="media_123",
            blob_name="videos/test.mp4",
            user_id=user.id,
            file_size=4096,
            preset="quality",
            max_frames=500,
            pipeline_config={
                "use_scene_detection": True,
                "use_hierarchical_summary": True,
            },
            optimized_pipeline=True,
        )
        assert response.job_id == "job-123"
        assert response.status == "queued"

    @pytest.mark.asyncio
    async def test_dispatch_failure_log_omits_user_controlled_values(self, caplog):
        """Dispatch fallback should not emit user-controlled IDs or exception text."""
        mod = _import_chunked_upload_module()

        raw_ids = ["block-0001"]
        b64_ids = [base64.b64encode(rid.encode()).decode() for rid in raw_ids]

        blob_service, db_service = _build_commit_dependencies()
        dispatch_service = MagicMock()
        dispatch_service.dispatch_video = AsyncMock(
            side_effect=RuntimeError("boom\nforged log line")
        )
        user = _make_user()
        malicious_media_id = "media-123\nforged log line"

        request = mod.CommitUploadRequest(
            upload_id="upload-1",
            media_id=malicious_media_id,
            blob_name="videos/test.mp4",
            block_ids=b64_ids,
            use_scene_detection=False,
            use_hierarchical_summary=False,
        )

        with (
            patch.object(mod, "get_blob_service", return_value=blob_service),
            patch.object(mod, "get_database_service", return_value=db_service),
            patch.object(mod, "get_storage_container_name", return_value="media"),
            patch.object(
                mod,
                "get_video_processing_dispatch_service",
                return_value=dispatch_service,
            ),
            caplog.at_level(logging.WARNING, logger=mod.logger.name),
        ):
            response = await mod.commit_chunked_upload(request=request, current_user=user)

        assert response.status == "uploaded"
        assert malicious_media_id not in caplog.text
        assert "boom" not in caplog.text
        assert "forged log line" not in caplog.text
