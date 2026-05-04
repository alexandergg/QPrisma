import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from functions.video_dispatch_bridge.contracts import (
    DatabricksStatusEvent,
    PayloadValidationError,
    VideoDispatchPayload,
)
from functions.video_dispatch_bridge.databricks_client import (
    DatabricksApiError,
    DatabricksJobsClient,
    DatabricksRunResult,
)
from functions.video_dispatch_bridge.processor import VideoDispatchBridge
from functions.video_dispatch_bridge.source_media_stager import (
    DatabricksSourceMediaStager,
    SourceMediaStagingError,
    SourceMediaStagingResult,
    build_volume_path,
)


def _payload(**overrides):
    payload = {
        "schema_version": "2026-05-01",
        "dispatch_id": "dbx-dispatch-1",
        "media_id": "media-1",
        "blob_name": "media-1.mp4",
        "source_media": {
            "storage_account_url": "https://storage.blob.core.windows.net",
            "container_name": "media",
            "blob_name": "media-1.mp4",
            "blob_url": "https://storage.blob.core.windows.net/media/media-1.mp4",
            "auth": {"mode": "managed_identity"},
        },
        "user_id": "user-1",
        "pipeline_config": {"preset": "balanced"},
        "databricks": {"video_job_id": "123"},
    }
    payload.update(overrides)
    return payload


def _settings(**overrides):
    settings = {
        "databricks_video_job_id": "123",
        "databricks_sql_warehouse_id": "warehouse-1",
        "databricks_outbox_catalog": "dbw_qprisma_dev",
        "databricks_outbox_schema": "video",
        "databricks_outbox_table": "video_pipeline_outbox",
        "databricks_outbox_poll_batch_size": 10,
        "databricks_staging_enabled": False,
        "databricks_source_volume_catalog": "dbw_qprisma_dev",
        "databricks_source_volume_schema": "video",
        "databricks_source_volume_name": "source_media",
        "databricks_source_volume_prefix": "",
        "azure_storage_managed_identity_client_id": None,
    }
    settings.update(overrides)
    return SimpleNamespace(**settings)


def test_function_app_imports_from_function_root(monkeypatch):
    function_root = Path(__file__).parents[1] / "functions" / "video_dispatch_bridge"

    class FakeFunctionApp:
        def __init__(self):
            self.registered_functions = []

        def service_bus_queue_trigger(self, **kwargs):
            return self._register("service_bus_queue_trigger", kwargs)

        def timer_trigger(self, **kwargs):
            return self._register("timer_trigger", kwargs)

        def _register(self, trigger_type, kwargs):
            def decorator(handler):
                self.registered_functions.append((trigger_type, kwargs, handler.__name__))
                return handler

            return decorator

    fake_azure = types.ModuleType("azure")
    fake_functions = types.ModuleType("azure.functions")
    fake_functions.FunctionApp = FakeFunctionApp
    fake_functions.ServiceBusMessage = object
    fake_functions.TimerRequest = object
    fake_azure.functions = fake_functions

    monkeypatch.setitem(sys.modules, "azure", fake_azure)
    monkeypatch.setitem(sys.modules, "azure.functions", fake_functions)
    monkeypatch.syspath_prepend(str(function_root))

    top_level_modules = [
        "function_app",
        "processor",
        "outbox",
        "state_store",
        "databricks_client",
        "source_media_stager",
        "contracts",
        "settings",
    ]
    for module_name in top_level_modules:
        sys.modules.pop(module_name, None)

    try:
        module = importlib.import_module("function_app")
        registrations = module.app.registered_functions
        assert [registration[0] for registration in registrations] == [
            "service_bus_queue_trigger",
            "timer_trigger",
        ]
        assert [registration[2] for registration in registrations] == [
            "video_dispatch_bridge",
            "video_outbox_projection",
        ]
    finally:
        for module_name in top_level_modules:
            sys.modules.pop(module_name, None)


def test_video_dispatch_payload_validates_required_fields():
    payload = _payload(media_id="")

    with pytest.raises(PayloadValidationError, match="media_id"):
        VideoDispatchPayload.from_json(json.dumps(payload))


def test_video_dispatch_payload_builds_databricks_run_request():
    payload = VideoDispatchPayload.from_json(json.dumps(_payload()))

    request = payload.databricks_parameters(default_job_id="")

    assert request["job_id"] == "123"
    assert request["idempotency_token"] == "dbx-dispatch-1"
    assert request["job_parameters"]["media_id"] == "media-1"
    assert json.loads(request["job_parameters"]["source_media"])["container_name"] == "media"


def test_video_dispatch_payload_accepts_volume_source_media():
    payload = _payload(
        source_media={
            "volume_path": "/Volumes/dbw_qprisma_dev/video/source_media/media-1.mp4",
            "auth": {"mode": "managed_identity"},
        }
    )

    parsed = VideoDispatchPayload.from_json(json.dumps(payload))
    request = parsed.databricks_parameters(default_job_id="")

    assert json.loads(request["job_parameters"]["source_media"])["volume_path"].startswith(
        "/Volumes/dbw_qprisma_dev/video/source_media/"
    )


def test_video_dispatch_payload_can_be_enriched_with_source_media():
    payload = VideoDispatchPayload.from_json(json.dumps(_payload()))

    enriched = payload.with_source_media(
        {
            **payload.source_media,
            "volume_path": "/Volumes/dbw_qprisma_dev/video/source_media/media-1.mp4",
        }
    )

    assert "volume_path" not in payload.source_media
    assert enriched.source_media["volume_path"].startswith("/Volumes/dbw_qprisma_dev/")


def test_build_volume_path_is_deterministic_and_sanitized():
    payload = VideoDispatchPayload.from_json(
        json.dumps(
            _payload(
                media_id="media 1",
                source_media={
                    "storage_account_url": "https://storage.blob.core.windows.net",
                    "container_name": "media",
                    "blob_name": "uploads/raw video!.mp4",
                    "blob_url": "https://storage.blob.core.windows.net/media/uploads/raw%20video!.mp4",
                    "auth": {"mode": "managed_identity"},
                },
            )
        )
    )

    assert (
        build_volume_path(payload, _settings())
        == "/Volumes/dbw_qprisma_dev/video/source_media/media_1/raw_video_.mp4"
    )


@pytest.mark.asyncio
async def test_source_media_stager_uploads_blob_to_volume_path():
    payload = VideoDispatchPayload.from_json(json.dumps(_payload()))
    databricks_client = MagicMock()
    databricks_client.create_directory = AsyncMock()
    databricks_client.upload_file = AsyncMock()

    class FakeChunkReader:
        async def chunks(self, source_media):
            assert source_media["container_name"] == "media"
            yield b"chunk-1"
            yield b"chunk-2"

    stager = DatabricksSourceMediaStager(
        settings=_settings(),
        databricks_client=databricks_client,
        chunk_reader=FakeChunkReader(),
    )

    result = await stager.stage(payload)

    assert result.volume_path == ("/Volumes/dbw_qprisma_dev/video/source_media/media-1/media-1.mp4")
    databricks_client.create_directory.assert_awaited_once_with(
        "/Volumes/dbw_qprisma_dev/video/source_media/media-1"
    )
    upload_args = databricks_client.upload_file.await_args.args
    assert upload_args[0] == result.volume_path
    assert [chunk async for chunk in upload_args[1]] == [b"chunk-1", b"chunk-2"]
    assert databricks_client.upload_file.await_args.kwargs == {"overwrite": True}
    assert result.source_media["volume_path"] == result.volume_path
    assert result.source_media["staging"]["status"] == "completed"


@pytest.mark.asyncio
async def test_source_media_stager_reuses_existing_volume_path_without_upload():
    payload = VideoDispatchPayload.from_json(json.dumps(_payload()))
    databricks_client = MagicMock()
    databricks_client.create_directory = AsyncMock()
    databricks_client.upload_file = AsyncMock()
    stager = DatabricksSourceMediaStager(
        settings=_settings(),
        databricks_client=databricks_client,
        chunk_reader=MagicMock(),
    )

    result = await stager.stage(payload, existing_volume_path="/Volumes/existing/media-1.mp4")

    assert result.volume_path == "/Volumes/existing/media-1.mp4"
    databricks_client.create_directory.assert_not_called()
    databricks_client.upload_file.assert_not_called()


@pytest.mark.asyncio
async def test_source_media_stager_requires_blob_source_fields():
    payload = VideoDispatchPayload.from_json(
        json.dumps(
            _payload(
                source_media={
                    "uri": "wasbs://media@storage.blob.core.windows.net/media-1.mp4",
                    "auth": {"mode": "managed_identity"},
                }
            )
        )
    )
    stager = DatabricksSourceMediaStager(
        settings=_settings(),
        databricks_client=MagicMock(),
        chunk_reader=MagicMock(),
    )

    with pytest.raises(SourceMediaStagingError, match="storage_account_url"):
        await stager.stage(payload)


def test_databricks_status_event_parses_json_payload_fields():
    event = DatabricksStatusEvent.from_json(
        json.dumps(
            {
                "schema_version": "2026-05-01",
                "media_id": "media-1",
                "dispatch_id": "dbx-dispatch-1",
                "status": "completed",
                "progress": 1.0,
                "message": "done",
                "processing_result": json.dumps({"backend": "databricks"}),
            }
        )
    )

    assert event.status == "completed"
    assert event.processing_result["backend"] == "databricks"


def test_databricks_status_event_rejects_invalid_progress():
    with pytest.raises(PayloadValidationError, match="progress"):
        DatabricksStatusEvent.from_json(
            json.dumps(
                {
                    "schema_version": "2026-05-01",
                    "media_id": "media-1",
                    "dispatch_id": "dbx-dispatch-1",
                    "status": "running",
                    "progress": 2,
                    "message": "bad",
                }
            )
        )


@pytest.mark.asyncio
async def test_databricks_client_creates_uc_volume_directory_with_encoded_path():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(409, text="already exists")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DatabricksJobsClient(
        settings=_settings(
            databricks_workspace_url="https://example.cloud.databricks.com",
            databricks_auth_type="pat",
            databricks_token="token",
            http_timeout_seconds=5,
        ),
        http_client=http_client,
    )

    try:
        await client.create_directory("/Volumes/catalog/schema/source_media/media 1")
    finally:
        await http_client.aclose()

    assert requests[0].method == "PUT"
    assert requests[0].url.raw_path.decode() == (
        "/api/2.0/fs/directories/%2FVolumes%2Fcatalog%2Fschema%2Fsource_media%2F" "media%201"
    )
    assert requests[0].headers["authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_databricks_client_uploads_file_content_to_uc_volume_path():
    requests = []

    async def handler(request):
        requests.append(request)
        content = await request.aread()
        assert content == b"chunk-1chunk-2"
        return httpx.Response(200)

    async def chunks():
        yield b"chunk-1"
        yield b"chunk-2"

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DatabricksJobsClient(
        settings=_settings(
            databricks_workspace_url="https://example.cloud.databricks.com",
            databricks_auth_type="pat",
            databricks_token="token",
            http_timeout_seconds=5,
        ),
        http_client=http_client,
    )

    try:
        await client.upload_file(
            "/Volumes/catalog/schema/source_media/media-1/video.mp4",
            chunks(),
            overwrite=True,
        )
    finally:
        await http_client.aclose()

    assert requests[0].method == "PUT"
    assert requests[0].url.raw_path.decode() == (
        "/api/2.0/fs/files/%2FVolumes%2Fcatalog%2Fschema%2Fsource_media%2F"
        "media-1%2Fvideo.mp4?overwrite=true"
    )
    assert requests[0].url.params["overwrite"] == "true"
    assert requests[0].headers["content-type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_databricks_client_raises_on_uc_volume_upload_failure():
    async def handler(request):
        return httpx.Response(403, text="forbidden")

    async def chunks():
        yield b"content"

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DatabricksJobsClient(
        settings=_settings(
            databricks_workspace_url="https://example.cloud.databricks.com",
            databricks_auth_type="pat",
            databricks_token="token",
            http_timeout_seconds=5,
        ),
        http_client=http_client,
    )

    try:
        with pytest.raises(DatabricksApiError, match="file upload failed"):
            await client.upload_file(
                "/Volumes/catalog/schema/volume/file.mp4",
                chunks(),
                overwrite=True,
            )
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_bridge_skips_existing_databricks_run():
    settings = _settings()
    databricks_client = MagicMock()
    databricks_client.run_now = AsyncMock()
    state_store = MagicMock()
    state_store.get_existing_run.return_value = SimpleNamespace(databricks_run_id=456)

    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=databricks_client,
        state_store=state_store,
    )

    run_id = await bridge.process_message(json.dumps(_payload()))

    assert run_id == 456
    databricks_client.run_now.assert_not_called()
    state_store.mark_run_started.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_starts_databricks_run_and_updates_state():
    settings = _settings()
    databricks_client = MagicMock()
    databricks_client.run_now = AsyncMock(return_value=DatabricksRunResult(run_id=789))
    state_store = MagicMock()
    state_store.get_existing_run.return_value = None

    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=databricks_client,
        state_store=state_store,
    )

    run_id = await bridge.process_message(json.dumps(_payload()))

    assert run_id == 789
    run_request = databricks_client.run_now.await_args.args[0]
    assert run_request["idempotency_token"] == "dbx-dispatch-1"
    state_store.mark_run_started.assert_called_once()


@pytest.mark.asyncio
async def test_bridge_stages_source_media_before_starting_databricks_run():
    settings = _settings(databricks_staging_enabled=True)
    databricks_client = MagicMock()
    databricks_client.run_now = AsyncMock(return_value=DatabricksRunResult(run_id=789))
    state_store = MagicMock()
    state_store.get_existing_run.return_value = None
    state_store.get_staged_source_media.return_value = None
    source_media_stager = MagicMock()
    source_media_stager.stage = AsyncMock(
        return_value=SourceMediaStagingResult(
            volume_path="/Volumes/dbw_qprisma_dev/video/source_media/media-1.mp4",
            source_media={
                **_payload()["source_media"],
                "volume_path": "/Volumes/dbw_qprisma_dev/video/source_media/media-1.mp4",
                "staging": {
                    "status": "completed",
                    "volume_path": "/Volumes/dbw_qprisma_dev/video/source_media/media-1.mp4",
                },
            },
        )
    )
    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=databricks_client,
        state_store=state_store,
        source_media_stager=source_media_stager,
    )

    run_id = await bridge.process_message(json.dumps(_payload()))

    assert run_id == 789
    source_media_stager.stage.assert_awaited_once()
    state_store.mark_source_media_staged.assert_called_once()
    run_request = databricks_client.run_now.await_args.args[0]
    source_media = json.loads(run_request["job_parameters"]["source_media"])
    assert source_media["volume_path"].startswith("/Volumes/dbw_qprisma_dev/video/source_media/")


@pytest.mark.asyncio
async def test_bridge_passes_existing_staged_volume_path_to_stager():
    settings = _settings(databricks_staging_enabled=True)
    databricks_client = MagicMock()
    databricks_client.run_now = AsyncMock(return_value=DatabricksRunResult(run_id=789))
    state_store = MagicMock()
    state_store.get_existing_run.return_value = None
    state_store.get_staged_source_media.return_value = SimpleNamespace(
        volume_path="/Volumes/existing/media-1.mp4"
    )
    source_media_stager = MagicMock()
    source_media_stager.stage = AsyncMock(
        return_value=SourceMediaStagingResult(
            volume_path="/Volumes/existing/media-1.mp4",
            source_media={
                **_payload()["source_media"],
                "volume_path": "/Volumes/existing/media-1.mp4",
            },
        )
    )
    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=databricks_client,
        state_store=state_store,
        source_media_stager=source_media_stager,
    )

    await bridge.process_message(json.dumps(_payload()))

    assert source_media_stager.stage.await_args.kwargs == {
        "existing_volume_path": "/Volumes/existing/media-1.mp4"
    }


@pytest.mark.asyncio
async def test_bridge_does_not_start_run_when_source_media_staging_fails():
    settings = _settings(databricks_staging_enabled=True)
    databricks_client = MagicMock()
    databricks_client.run_now = AsyncMock()
    state_store = MagicMock()
    state_store.get_existing_run.return_value = None
    state_store.get_staged_source_media.return_value = None
    source_media_stager = MagicMock()
    source_media_stager.stage = AsyncMock(side_effect=SourceMediaStagingError("cannot stage"))
    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=databricks_client,
        state_store=state_store,
        source_media_stager=source_media_stager,
    )

    with pytest.raises(SourceMediaStagingError, match="cannot stage"):
        await bridge.process_message(json.dumps(_payload()))

    databricks_client.run_now.assert_not_called()
    state_store.mark_source_media_staged.assert_not_called()
    state_store.mark_run_started.assert_not_called()


def test_bridge_projects_databricks_status_event():
    settings = _settings()
    state_store = MagicMock()
    bridge = VideoDispatchBridge(
        settings=settings,
        databricks_client=MagicMock(),
        state_store=state_store,
    )

    bridge.process_status_event(
        json.dumps(
            {
                "schema_version": "2026-05-01",
                "media_id": "media-1",
                "dispatch_id": "dbx-dispatch-1",
                "status": "completed",
                "progress": 1.0,
                "message": "done",
                "processing_result": {"backend": "databricks"},
            }
        )
    )

    projected_event = state_store.apply_status_event.call_args.args[0]
    assert projected_event.media_id == "media-1"
    assert projected_event.status == "completed"


@pytest.mark.asyncio
async def test_bridge_polls_databricks_outbox_and_marks_consumed_after_projection():
    databricks_client = MagicMock()
    databricks_client.execute_sql_statement = AsyncMock(
        side_effect=[
            SimpleNamespace(
                rows=[
                    {
                        "outbox_id": "outbox-1",
                        "schema_version": "2026-05-01",
                        "media_id": "media-1",
                        "dispatch_id": "dbx-dispatch-1",
                        "status": "completed",
                        "progress": "1.0",
                        "message": "done",
                        "processing_result": json.dumps({"backend": "databricks"}),
                        "video_metadata": "{}",
                        "error": "{}",
                    }
                ]
            ),
            SimpleNamespace(rows=[]),
        ]
    )
    state_store = MagicMock()
    bridge = VideoDispatchBridge(
        settings=_settings(),
        databricks_client=databricks_client,
        state_store=state_store,
    )

    processed_count = await bridge.process_outbox_events()

    assert processed_count == 1
    projected_event = state_store.apply_status_event.call_args.args[0]
    assert projected_event.media_id == "media-1"
    assert projected_event.processing_result["backend"] == "databricks"
    update_statement = databricks_client.execute_sql_statement.await_args_list[1].args[0]
    assert "UPDATE `dbw_qprisma_dev`.`video`.`video_pipeline_outbox`" in update_statement
    assert "outbox-1" in update_statement


@pytest.mark.asyncio
async def test_bridge_does_not_mark_outbox_row_consumed_when_projection_fails():
    databricks_client = MagicMock()
    databricks_client.execute_sql_statement = AsyncMock(
        return_value=SimpleNamespace(
            rows=[
                {
                    "outbox_id": "outbox-1",
                    "schema_version": "2026-05-01",
                    "media_id": "media-1",
                    "dispatch_id": "dbx-dispatch-1",
                    "status": "completed",
                    "progress": "1.0",
                    "message": "done",
                    "processing_result": "{}",
                    "video_metadata": "{}",
                    "error": "{}",
                }
            ]
        )
    )
    state_store = MagicMock()
    state_store.apply_status_event.side_effect = RuntimeError("postgres unavailable")
    bridge = VideoDispatchBridge(
        settings=_settings(),
        databricks_client=databricks_client,
        state_store=state_store,
    )

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await bridge.process_outbox_events()

    assert databricks_client.execute_sql_statement.await_count == 1


@pytest.mark.asyncio
async def test_bridge_skips_outbox_polling_without_sql_warehouse():
    databricks_client = MagicMock()
    databricks_client.execute_sql_statement = AsyncMock()
    bridge = VideoDispatchBridge(
        settings=_settings(databricks_sql_warehouse_id=None),
        databricks_client=databricks_client,
        state_store=MagicMock(),
    )

    processed_count = await bridge.process_outbox_events()

    assert processed_count == 0
    databricks_client.execute_sql_statement.assert_not_called()
