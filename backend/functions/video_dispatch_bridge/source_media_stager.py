from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Protocol

if __package__:
    from .contracts import VideoDispatchPayload
    from .databricks_client import DatabricksJobsClient
    from .settings import BridgeSettings
else:
    from contracts import VideoDispatchPayload
    from databricks_client import DatabricksJobsClient
    from settings import BridgeSettings


class SourceMediaStagingError(RuntimeError):
    """Raised when uploaded source media cannot be staged into a UC volume."""


class SourceMediaChunkReader(Protocol):
    def chunks(self, source_media: dict[str, Any]) -> AsyncIterator[bytes]:
        """Return source Blob bytes as an async iterator."""


class AzureBlobSourceMediaChunkReader:
    def __init__(self, *, managed_identity_client_id: str | None = None) -> None:
        self._managed_identity_client_id = managed_identity_client_id

    async def chunks(self, source_media: dict[str, Any]) -> AsyncIterator[bytes]:
        from azure.identity.aio import DefaultAzureCredential
        from azure.storage.blob.aio import BlobClient

        credential_kwargs: dict[str, str] = {}
        if self._managed_identity_client_id:
            credential_kwargs["managed_identity_client_id"] = self._managed_identity_client_id

        async with DefaultAzureCredential(**credential_kwargs) as credential:
            blob_client = BlobClient(
                account_url=str(source_media["storage_account_url"]).rstrip("/"),
                container_name=source_media["container_name"],
                blob_name=source_media["blob_name"],
                credential=credential,
            )
            async with blob_client:
                downloader = await blob_client.download_blob()
                async for chunk in downloader.chunks():
                    yield bytes(chunk)


@dataclass(frozen=True)
class SourceMediaStagingResult:
    volume_path: str
    source_media: dict[str, Any]


class DatabricksSourceMediaStager:
    def __init__(
        self,
        *,
        settings: BridgeSettings,
        databricks_client: DatabricksJobsClient,
        chunk_reader: SourceMediaChunkReader | None = None,
    ) -> None:
        self._settings = settings
        self._databricks_client = databricks_client
        self._chunk_reader = chunk_reader or AzureBlobSourceMediaChunkReader(
            managed_identity_client_id=getattr(
                settings, "azure_storage_managed_identity_client_id", None
            )
        )

    async def stage(
        self,
        payload: VideoDispatchPayload,
        *,
        existing_volume_path: str | None = None,
    ) -> SourceMediaStagingResult:
        source_media = dict(payload.source_media)
        current_volume_path = _non_empty_string(source_media.get("volume_path"))
        volume_path = current_volume_path or existing_volume_path
        if volume_path:
            enriched_source_media = self._enriched_source_media(source_media, volume_path)
            return SourceMediaStagingResult(
                volume_path=volume_path,
                source_media=enriched_source_media,
            )

        _require_blob_source_media(source_media)
        volume_path = build_volume_path(payload, self._settings)
        await self._databricks_client.create_directory(_parent_directory(volume_path))
        await self._databricks_client.upload_file(
            volume_path,
            self._chunk_reader.chunks(source_media),
            overwrite=True,
        )

        enriched_source_media = self._enriched_source_media(source_media, volume_path)
        return SourceMediaStagingResult(
            volume_path=volume_path,
            source_media=enriched_source_media,
        )

    def _enriched_source_media(
        self,
        source_media: dict[str, Any],
        volume_path: str,
    ) -> dict[str, Any]:
        return {
            **source_media,
            "volume_path": volume_path,
            "staging": {
                "status": "completed",
                "method": "databricks_files_api",
                "volume_path": volume_path,
                "completed_at": datetime.now(UTC).isoformat(),
                "source": {
                    "storage_account_url": source_media.get("storage_account_url"),
                    "container_name": source_media.get("container_name"),
                    "blob_name": source_media.get("blob_name"),
                },
            },
        }


def build_volume_path(payload: VideoDispatchPayload, settings: BridgeSettings) -> str:
    catalog = _clean_uc_part(settings.databricks_source_volume_catalog, "catalog")
    schema = _clean_uc_part(settings.databricks_source_volume_schema, "schema")
    volume = _clean_uc_part(settings.databricks_source_volume_name, "volume")
    prefix = _clean_prefix(settings.databricks_source_volume_prefix)
    media_id = _clean_path_segment(payload.media_id) or "unknown-media"
    filename = _safe_blob_filename(payload.source_media.get("blob_name") or payload.blob_name)

    path_parts = ["/Volumes", catalog, schema, volume]
    if prefix:
        path_parts.extend(prefix.split("/"))
    path_parts.extend([media_id, filename])
    return "/" + "/".join(part.strip("/") for part in path_parts if part)


def _require_blob_source_media(source_media: dict[str, Any]) -> None:
    required = ("storage_account_url", "container_name", "blob_name")
    missing = [
        field
        for field in required
        if not isinstance(source_media.get(field), str) or not source_media[field].strip()
    ]
    if missing:
        raise SourceMediaStagingError(
            f"Cannot stage source media without Blob fields: {', '.join(missing)}"
        )


def _safe_blob_filename(blob_name: object) -> str:
    raw_name = str(blob_name or "").strip()
    filename = PurePosixPath(raw_name).name if raw_name else ""
    cleaned = _clean_path_segment(filename)
    return cleaned[:180] if cleaned else "source-media.bin"


def _clean_uc_part(value: str, label: str) -> str:
    cleaned = str(value or "").strip().strip("/")
    if not cleaned or "/" in cleaned:
        raise SourceMediaStagingError(f"Invalid Databricks source volume {label}: {value!r}")
    return cleaned


def _clean_prefix(value: str) -> str:
    raw_prefix = str(value or "").strip().strip("/")
    if not raw_prefix:
        return ""
    segments = [_clean_path_segment(segment) for segment in raw_prefix.split("/")]
    return "/".join(segment for segment in segments if segment)


def _clean_path_segment(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned.strip("._-")


def _parent_directory(volume_path: str) -> str:
    parent = volume_path.rsplit("/", 1)[0]
    if not parent:
        raise SourceMediaStagingError(f"Invalid volume path: {volume_path}")
    return parent


def _non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
