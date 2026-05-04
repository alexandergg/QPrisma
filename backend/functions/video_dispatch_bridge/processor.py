from __future__ import annotations

import logging

if __package__:
    from .contracts import DatabricksStatusEvent, VideoDispatchPayload
    from .databricks_client import DatabricksJobsClient
    from .outbox import DatabricksOutboxConsumer
    from .settings import BridgeSettings
    from .source_media_stager import DatabricksSourceMediaStager
    from .state_store import PostgresDispatchStateStore
else:
    from contracts import DatabricksStatusEvent, VideoDispatchPayload
    from databricks_client import DatabricksJobsClient
    from outbox import DatabricksOutboxConsumer
    from settings import BridgeSettings
    from source_media_stager import DatabricksSourceMediaStager
    from state_store import PostgresDispatchStateStore

logger = logging.getLogger(__name__)


class VideoDispatchBridge:
    def __init__(
        self,
        *,
        settings: BridgeSettings,
        databricks_client: DatabricksJobsClient | None = None,
        state_store: PostgresDispatchStateStore | None = None,
        source_media_stager: DatabricksSourceMediaStager | None = None,
    ) -> None:
        self._settings = settings
        self._databricks_client = databricks_client or DatabricksJobsClient(settings)
        self._state_store = state_store or PostgresDispatchStateStore(settings.database_url)
        self._staging_enabled = bool(getattr(settings, "databricks_staging_enabled", False))
        self._source_media_stager = source_media_stager
        if self._source_media_stager is None and self._staging_enabled:
            self._source_media_stager = DatabricksSourceMediaStager(
                settings=settings,
                databricks_client=self._databricks_client,
            )

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

        if self._staging_enabled:
            payload = await self._stage_source_media(payload)

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

    async def _stage_source_media(self, payload: VideoDispatchPayload) -> VideoDispatchPayload:
        if self._source_media_stager is None:
            raise RuntimeError(
                "Databricks source media staging is enabled but no stager is configured"
            )
        existing_staged_source_media = self._state_store.get_staged_source_media(payload)
        staging_result = await self._source_media_stager.stage(
            payload,
            existing_volume_path=(
                existing_staged_source_media.volume_path if existing_staged_source_media else None
            ),
        )
        self._state_store.mark_source_media_staged(payload, staging_result.source_media)
        logger.info(
            "Databricks source media staged",
            extra={
                "media_id": payload.media_id,
                "dispatch_id": payload.dispatch_id,
                "volume_path": staging_result.volume_path,
            },
        )
        return payload.with_source_media(staging_result.source_media)

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
