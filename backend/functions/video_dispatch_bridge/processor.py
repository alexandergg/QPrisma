from __future__ import annotations

import logging

from .contracts import DatabricksStatusEvent, VideoDispatchPayload
from .databricks_client import DatabricksJobsClient
from .outbox import DatabricksOutboxConsumer
from .settings import BridgeSettings
from .state_store import PostgresDispatchStateStore

logger = logging.getLogger(__name__)


class VideoDispatchBridge:
    def __init__(
        self,
        *,
        settings: BridgeSettings,
        databricks_client: DatabricksJobsClient | None = None,
        state_store: PostgresDispatchStateStore | None = None,
    ) -> None:
        self._settings = settings
        self._databricks_client = databricks_client or DatabricksJobsClient(settings)
        self._state_store = state_store or PostgresDispatchStateStore(settings.database_url)

    async def process_message(self, raw_body: bytes | str) -> int:
        payload = VideoDispatchPayload.from_json(raw_body)
        existing_run = self._state_store.get_existing_run(payload)
        if existing_run is not None:
            logger.info(
                "Databricks dispatch already started",
                extra={
                    "media_id": payload.media_id,
                    "dispatch_id": payload.dispatch_id,
                    "databricks_run_id": existing_run.databricks_run_id,
                },
            )
            return existing_run.databricks_run_id

        run_request = payload.databricks_parameters(self._settings.databricks_video_job_id)
        run_result = await self._databricks_client.run_now(run_request)
        self._state_store.mark_run_started(payload, run_result.run_id)

        logger.info(
            "Databricks run started",
            extra={
                "media_id": payload.media_id,
                "dispatch_id": payload.dispatch_id,
                "databricks_run_id": run_result.run_id,
            },
        )
        return run_result.run_id

    def process_status_event(self, raw_body: bytes | str) -> None:
        event = DatabricksStatusEvent.from_json(raw_body)
        self._state_store.apply_status_event(event)
        logger.info(
            "Databricks status projected",
            extra={
                "media_id": event.media_id,
                "dispatch_id": event.dispatch_id,
                "status": event.status,
                "progress": event.progress,
            },
        )

    async def process_outbox_events(self) -> int:
        consumer = DatabricksOutboxConsumer(
            settings=self._settings,
            databricks_client=self._databricks_client,
            state_store=self._state_store,
        )
        return await consumer.process_once()
