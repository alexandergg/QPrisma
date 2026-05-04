import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.video_processing_dispatch_service import (
    VideoProcessingDispatchError,
    VideoProcessingDispatchService,
)


def _settings(
    *,
    backend: str = "celery",
    namespace: str | None = None,
    queue_name: str = "video-processing",
    managed_identity_client_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        processing=SimpleNamespace(backend=backend),
        service_bus=SimpleNamespace(
            fully_qualified_namespace=namespace,
            video_processing_queue_name=queue_name,
            managed_identity_client_id=managed_identity_client_id,
        ),
        azure=SimpleNamespace(
            storage_account_url="https://qprismastorage.blob.core.windows.net",
            storage_container_name="media",
        ),
        databricks=SimpleNamespace(
            workspace_url="https://example.azuredatabricks.net",
            video_job_id="123",
            lakehouse_storage_account="qprismalake",
            lakehouse_dfs_endpoint="https://qprismalake.dfs.core.windows.net/",
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_video_uses_celery_backend(monkeypatch):
    async_result = MagicMock(id="celery-job-1")
    process_video_pipeline = MagicMock()
    process_video_pipeline.apply_async.return_value = async_result

    tasks_module = types.ModuleType("tasks")
    video_tasks_module = types.ModuleType("tasks.video_tasks")
    video_tasks_module.process_video_pipeline = process_video_pipeline
    monkeypatch.setitem(sys.modules, "tasks", tasks_module)
    monkeypatch.setitem(sys.modules, "tasks.video_tasks", video_tasks_module)

    service = VideoProcessingDispatchService(_settings())

    result = await service.dispatch_video(
        media_id="media-1",
        blob_name="media-1.mp4",
        user_id="user-1",
        file_size=1024,
        preset="balanced",
        max_frames=150,
        pipeline_config={"use_scene_detection": True},
        optimized_pipeline=True,
    )

    process_video_pipeline.apply_async.assert_called_once()
    assert result.job_id == "celery-job-1"
    assert result.backend == "celery"
    assert result.media_updates()["processing_method"] == "celery"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_logs_omit_user_controlled_media_id(monkeypatch, caplog):
    async_result = MagicMock(id="celery-job-1")
    process_video_pipeline = MagicMock()
    process_video_pipeline.apply_async.return_value = async_result

    tasks_module = types.ModuleType("tasks")
    video_tasks_module = types.ModuleType("tasks.video_tasks")
    video_tasks_module.process_video_pipeline = process_video_pipeline
    monkeypatch.setitem(sys.modules, "tasks", tasks_module)
    monkeypatch.setitem(sys.modules, "tasks.video_tasks", video_tasks_module)

    service = VideoProcessingDispatchService(_settings())
    malicious_media_id = "media-1\nforged log line"

    with caplog.at_level("INFO", logger="services.video_processing_dispatch_service"):
        await service.dispatch_video(
            media_id=malicious_media_id,
            blob_name="media-1.mp4",
            user_id="user-1",
            file_size=1024,
            preset="balanced",
            max_frames=150,
            pipeline_config={},
            optimized_pipeline=True,
        )

    assert malicious_media_id not in caplog.text
    assert "forged log line" not in caplog.text
    assert all(not hasattr(record, "media_id") for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_video_requires_service_bus_namespace_for_databricks():
    service = VideoProcessingDispatchService(_settings(backend="databricks"))

    with pytest.raises(VideoProcessingDispatchError):
        await service.dispatch_video(
            media_id="media-1",
            blob_name="media-1.mp4",
            user_id="user-1",
            file_size=1024,
            preset="balanced",
            max_frames=150,
            pipeline_config={},
            optimized_pipeline=True,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_video_publishes_databricks_service_bus_message():
    service = VideoProcessingDispatchService(
        _settings(backend="databricks", namespace="qprisma.servicebus.windows.net")
    )
    service._send_service_bus_message = AsyncMock()  # type: ignore[method-assign]

    result = await service.dispatch_video(
        media_id="media-1",
        blob_name="media-1.mp4",
        user_id="user-1",
        file_size=1024,
        preset="balanced",
        max_frames=150,
        pipeline_config={"use_scene_detection": True},
        optimized_pipeline=True,
    )

    service._send_service_bus_message.assert_awaited_once()
    call_kwargs = service._send_service_bus_message.await_args.kwargs
    assert call_kwargs["namespace"] == "qprisma.servicebus.windows.net"
    assert call_kwargs["queue_name"] == "video-processing"
    assert call_kwargs["correlation_id"] == "media-1"
    assert call_kwargs["payload"]["media_id"] == "media-1"
    assert call_kwargs["payload"]["source_media"] == {
        "storage_account_url": "https://qprismastorage.blob.core.windows.net",
        "container_name": "media",
        "blob_name": "media-1.mp4",
        "blob_url": "https://qprismastorage.blob.core.windows.net/media/media-1.mp4",
        "auth": {
            "mode": "managed_identity",
            "required_role": "Storage Blob Data Reader",
        },
    }
    assert call_kwargs["payload"]["databricks"]["video_job_id"] == "123"
    assert result.pipeline_config["dispatch"]["source_media"] == {
        "container_name": "media",
        "blob_name": "media-1.mp4",
        "auth_mode": "managed_identity",
    }
    assert result.job_id.startswith("dbx-")
    assert result.backend == "databricks"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_bus_dispatch_log_omits_user_controlled_media_id(caplog):
    service = VideoProcessingDispatchService(
        _settings(backend="databricks", namespace="qprisma.servicebus.windows.net")
    )
    service._send_service_bus_message = AsyncMock()  # type: ignore[method-assign]
    malicious_media_id = "media-1\nforged log line"

    with caplog.at_level("INFO", logger="services.video_processing_dispatch_service"):
        await service.dispatch_video(
            media_id=malicious_media_id,
            blob_name="media-1.mp4",
            user_id="user-1",
            file_size=1024,
            preset="balanced",
            max_frames=150,
            pipeline_config={},
            optimized_pipeline=True,
        )

    assert malicious_media_id not in caplog.text
    assert "forged log line" not in caplog.text
    assert all(not hasattr(record, "media_id") for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_service_bus_message_pins_configured_managed_identity(monkeypatch):
    credential_kwargs: dict[str, str] = {}
    sent_messages = []

    class FakeCredential:
        def __init__(self, **kwargs):
            credential_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeMessage:
        def __init__(self, body, **kwargs):
            self.body = body
            self.kwargs = kwargs

    class FakeSender:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send_messages(self, message):
            sent_messages.append(message)

    class FakeServiceBusClient:
        def __init__(self, *, fully_qualified_namespace, credential):
            self.fully_qualified_namespace = fully_qualified_namespace
            self.credential = credential

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get_queue_sender(self, *, queue_name):
            assert queue_name == "video-processing"
            return FakeSender()

    azure_module = types.ModuleType("azure")
    identity_module = types.ModuleType("azure.identity")
    identity_aio_module = types.ModuleType("azure.identity.aio")
    identity_aio_module.DefaultAzureCredential = FakeCredential
    servicebus_module = types.ModuleType("azure.servicebus")
    servicebus_module.ServiceBusMessage = FakeMessage
    servicebus_aio_module = types.ModuleType("azure.servicebus.aio")
    servicebus_aio_module.ServiceBusClient = FakeServiceBusClient

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_module)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", identity_aio_module)
    monkeypatch.setitem(sys.modules, "azure.servicebus", servicebus_module)
    monkeypatch.setitem(sys.modules, "azure.servicebus.aio", servicebus_aio_module)

    service = VideoProcessingDispatchService(
        _settings(
            backend="databricks",
            namespace="qprisma.servicebus.windows.net",
            managed_identity_client_id="client-id-123",
        )
    )

    await service._send_service_bus_message(
        namespace="qprisma.servicebus.windows.net",
        queue_name="video-processing",
        message_id="dispatch-1",
        correlation_id="media-1",
        payload={"media_id": "media-1"},
    )

    assert credential_kwargs == {"managed_identity_client_id": "client-id-123"}
    assert sent_messages[0].kwargs["message_id"] == "dispatch-1"
