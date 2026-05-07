from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.exceptions import NotFoundError
from services.media_library_service import MediaLibraryService


async def _empty_hydrate(item: dict) -> dict:
    return item


@pytest.mark.unit
async def test_missing_media_uses_core_not_found_error():
    db = MagicMock()
    db.get_media.return_value = None
    service = MediaLibraryService(
        db=db,
        blob_service=MagicMock(),
        container_name="media",
        sas_url_factory=AsyncMock(return_value=None),
        hydrate_data_factory=_empty_hydrate,
    )

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_media_metadata(media_id="media_123", user_id="user_123")

    assert exc_info.value.details["resource_type"] == "Media"
    assert exc_info.value.details["resource_id"] == "media_123"


@pytest.mark.unit
async def test_delete_media_runs_sync_graph_delete_in_executor():
    media = MagicMock()
    media.user_id = "user_123"
    media.blob_name = "video.mp4"

    db = MagicMock()
    db.get_media.return_value = media

    blob_service = MagicMock()
    graph_service = MagicMock()
    executor_calls = []

    class FakeLoop:
        async def run_in_executor(self, executor, func, *args):
            executor_calls.append((func, args))
            return func(*args)

    service = MediaLibraryService(
        db=db,
        blob_service=blob_service,
        container_name="media",
        sas_url_factory=AsyncMock(return_value=None),
        graph_service_factory=lambda: graph_service,
    )

    with patch("services.media_library_service.asyncio.get_running_loop", return_value=FakeLoop()):
        await service.delete_media(media_id="media_123", user_id="user_123")

    assert (graph_service.delete_video_graph, ("media_123",)) in executor_calls
    graph_service.delete_video_graph.assert_called_once_with("media_123")
