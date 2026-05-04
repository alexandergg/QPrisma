"""Dispatch video processing work to the configured backend."""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from core.config import settings

logger = logging.getLogger(__name__)


class VideoProcessingDispatchError(RuntimeError):
    """Raised when video processing work cannot be dispatched."""


@dataclass(frozen=True)
class VideoProcessingDispatchResult:
    """Result returned after a processing dispatch attempt."""

    job_id: str
    backend: str
    pipeline_config: dict[str, Any]

    def media_updates(self) -> dict[str, Any]:
        """Build database updates compatible with the existing media model."""
        return {
            "job_id": self.job_id,
            "processing_method": self.backend,
            "processing_status": "queued",
            "pipeline_config": self.pipeline_config,
        }


class VideoProcessingDispatchService:
    """Dispatch video processing to Celery or the Databricks pilot queue."""

    def __init__(self, app_settings=settings):
        self._settings = app_settings

    async def dispatch_video(
        self,
        *,
        media_id: str,
        blob_name: str,
        user_id: str,
        file_size: int | None,
        preset: str | None,
        max_frames: int | None,
        pipeline_config: dict[str, Any],
        optimized_pipeline: bool,
        custom_prompt: str | None = None,
        index_graph: bool = True,
    ) -> VideoProcessingDispatchResult:
        """Dispatch a video processing job using the configured backend."""
        backend = self._settings.processing.backend
        if backend == "celery":
            return self._dispatch_celery(
                media_id=media_id,
                blob_name=blob_name,
                preset=preset,
                max_frames=max_frames,
                pipeline_config=pipeline_config,
                optimized_pipeline=optimized_pipeline,
                custom_prompt=custom_prompt,
                index_graph=index_graph,
            )

        return await self._dispatch_databricks_queue(
            media_id=media_id,
            blob_name=blob_name,
            user_id=user_id,
            file_size=file_size,
            preset=preset,
            max_frames=max_frames,
            pipeline_config=pipeline_config,
            optimized_pipeline=optimized_pipeline,
            custom_prompt=custom_prompt,
            index_graph=index_graph,
        )

    def _dispatch_celery(
        self,
        *,
        media_id: str,
        blob_name: str,
        preset: str | None,
        max_frames: int | None,
        pipeline_config: dict[str, Any],
        optimized_pipeline: bool,
        custom_prompt: str | None,
        index_graph: bool,
    ) -> VideoProcessingDispatchResult:
        """Dispatch to the existing Celery pipeline."""
        from tasks.video_tasks import process_video_pipeline

        celery_config = {
            "max_frames": max_frames,
            "custom_prompt": custom_prompt,
            "index_graph": index_graph,
            "preset": preset,
        }
        if optimized_pipeline:
            celery_config["optimized_pipeline"] = True
            celery_config["pipeline_config"] = pipeline_config

        async_result = process_video_pipeline.apply_async(args=[media_id, blob_name, celery_config])
        enriched_config = {
            **pipeline_config,
            "dispatch": {
                "backend": "celery",
                "task_id": async_result.id,
                "queued_at": datetime.now(UTC).isoformat(),
            },
        }
        logger.info("Queued video processing via Celery")
        return VideoProcessingDispatchResult(
            job_id=async_result.id,
            backend="celery",
            pipeline_config=enriched_config,
        )

    async def _dispatch_databricks_queue(
        self,
        *,
        media_id: str,
        blob_name: str,
        user_id: str,
        file_size: int | None,
        preset: str | None,
        max_frames: int | None,
        pipeline_config: dict[str, Any],
        optimized_pipeline: bool,
        custom_prompt: str | None,
        index_graph: bool,
    ) -> VideoProcessingDispatchResult:
        """Publish a durable event for the Databricks video pipeline."""
        namespace = self._settings.service_bus.fully_qualified_namespace
        queue_name = self._settings.service_bus.video_processing_queue_name
        if not namespace:
            raise VideoProcessingDispatchError(
                "SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE is required for Databricks dispatch"
            )

        dispatch_id = f"dbx-{uuid.uuid4()}"
        queued_at = datetime.now(UTC).isoformat()
        source_media = self._build_source_media_contract(blob_name)
        payload = {
            "schema_version": "2026-05-01",
            "dispatch_id": dispatch_id,
            "media_id": media_id,
            "blob_name": blob_name,
            "source_media": source_media,
            "user_id": user_id,
            "file_size": file_size,
            "preset": preset,
            "max_frames": max_frames,
            "custom_prompt": custom_prompt,
            "index_graph": index_graph,
            "optimized_pipeline": optimized_pipeline,
            "pipeline_config": pipeline_config,
            "databricks": {
                "workspace_url": self._settings.databricks.workspace_url,
                "video_job_id": self._settings.databricks.video_job_id,
                "lakehouse_storage_account": self._settings.databricks.lakehouse_storage_account,
                "lakehouse_dfs_endpoint": self._settings.databricks.lakehouse_dfs_endpoint,
            },
            "queued_at": queued_at,
        }

        await self._send_service_bus_message(
            namespace=namespace,
            queue_name=queue_name,
            message_id=dispatch_id,
            correlation_id=media_id,
            payload=payload,
        )

        enriched_config = {
            **pipeline_config,
            "dispatch": {
                "backend": self._settings.processing.backend,
                "dispatch_id": dispatch_id,
                "service_bus_queue": queue_name,
                "databricks_video_job_id": self._settings.databricks.video_job_id,
                "source_media": {
                    "container_name": source_media["container_name"],
                    "blob_name": source_media["blob_name"],
                    "auth_mode": source_media["auth"]["mode"],
                },
                "queued_at": queued_at,
            },
        }
        logger.info("Queued video processing via Service Bus")
        return VideoProcessingDispatchResult(
            job_id=dispatch_id,
            backend=self._settings.processing.backend,
            pipeline_config=enriched_config,
        )

    def _build_source_media_contract(self, blob_name: str) -> dict[str, Any]:
        """Build the explicit storage contract Databricks consumers use to read media."""
        storage_account_url = self._settings.azure.storage_account_url
        container_name = self._settings.azure.storage_container_name
        if not storage_account_url:
            raise VideoProcessingDispatchError(
                "AZURE_STORAGE_ACCOUNT_URL is required for Databricks dispatch"
            )
        if not container_name:
            raise VideoProcessingDispatchError(
                "AZURE_STORAGE_CONTAINER_NAME is required for Databricks dispatch"
            )

        account_url = storage_account_url.rstrip("/")
        encoded_blob_name = quote(blob_name, safe="/")
        return {
            "storage_account_url": account_url,
            "container_name": container_name,
            "blob_name": blob_name,
            "blob_url": f"{account_url}/{container_name}/{encoded_blob_name}",
            "auth": {
                "mode": "managed_identity",
                "required_role": "Storage Blob Data Reader",
            },
        }

    async def _send_service_bus_message(
        self,
        *,
        namespace: str,
        queue_name: str,
        message_id: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Send a JSON payload to Service Bus with managed identity."""
        from azure.identity.aio import DefaultAzureCredential
        from azure.servicebus import ServiceBusMessage
        from azure.servicebus.aio import ServiceBusClient

        credential_kwargs: dict[str, str] = {}
        managed_identity_client_id = self._settings.service_bus.managed_identity_client_id
        if managed_identity_client_id:
            credential_kwargs["managed_identity_client_id"] = managed_identity_client_id

        async with (
            DefaultAzureCredential(**credential_kwargs) as credential,
            ServiceBusClient(
                fully_qualified_namespace=namespace,
                credential=credential,
            ) as client,
        ):
            sender = client.get_queue_sender(queue_name=queue_name)
            async with sender:
                await sender.send_messages(
                    ServiceBusMessage(
                        json.dumps(payload),
                        content_type="application/json",
                        message_id=message_id,
                        correlation_id=correlation_id,
                        application_properties={
                            "media_id": payload["media_id"],
                            "backend": self._settings.processing.backend,
                        },
                    )
                )


_dispatch_service: VideoProcessingDispatchService | None = None


def get_video_processing_dispatch_service() -> VideoProcessingDispatchService:
    """Return the lazy singleton video processing dispatch service."""
    global _dispatch_service
    if _dispatch_service is None:
        _dispatch_service = VideoProcessingDispatchService()
    return _dispatch_service
