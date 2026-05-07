from io import BytesIO
from unittest.mock import MagicMock

import pytest

from core.exceptions import BadRequestError
from services.media_upload_service import DIRECT_UPLOAD_MAX_BYTES, MediaUploadService


def _build_service(blob_service: MagicMock | None = None) -> MediaUploadService:
    return MediaUploadService(
        blob_service=blob_service or MagicMock(),
        db=MagicMock(),
        container_name="media",
        dispatch_service_factory=MagicMock(),
    )


def _build_upload_file(*, size: int | None) -> MagicMock:
    upload_file = MagicMock()
    upload_file.filename = "video.mp4"
    upload_file.content_type = "video/mp4"
    upload_file.size = size
    upload_file.file = BytesIO(b"")
    return upload_file


@pytest.mark.unit
@pytest.mark.parametrize("size", [None, 0])
async def test_direct_upload_rejects_unknown_or_zero_size_before_blob_persistence(size):
    blob_service = MagicMock()
    service = _build_service(blob_service)

    with pytest.raises(BadRequestError) as exc_info:
        await service._upload_blob(file=_build_upload_file(size=size), blob_name="media.mp4")

    assert exc_info.value.details["status_code"] == 413
    assert "chunked upload" in exc_info.value.message
    blob_service.get_blob_client.assert_not_called()


@pytest.mark.unit
async def test_direct_upload_rejects_oversized_file_before_blob_persistence():
    blob_service = MagicMock()
    service = _build_service(blob_service)

    with pytest.raises(BadRequestError) as exc_info:
        await service._upload_blob(
            file=_build_upload_file(size=DIRECT_UPLOAD_MAX_BYTES + 1),
            blob_name="media.mp4",
        )

    assert exc_info.value.details["status_code"] == 413
    assert "exceeds the direct upload size limit" in exc_info.value.message
    blob_service.get_blob_client.assert_not_called()
