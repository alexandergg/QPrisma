import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from functions.video_dispatch_bridge.contracts import (
    DatabricksStatusEvent,
    PayloadValidationError,
    VideoDispatchPayload,
)
from functions.video_dispatch_bridge.databricks_client import DatabricksRunResult
from functions.video_dispatch_bridge.processor import VideoDispatchBridge


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
        "databricks_outbox_catalog": "qprisma_dev",
        "databricks_outbox_schema": "video",
        "databricks_outbox_table": "video_pipeline_outbox",
        "databricks_outbox_poll_batch_size": 10,
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
    assert "UPDATE `qprisma_dev`.`video`.`video_pipeline_outbox`" in update_statement
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
