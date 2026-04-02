"""Service for durable storage and fast retrieval of large tool outputs."""

import asyncio
import gzip
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from azure.storage.blob import BlobServiceClient, ContentSettings

from core.config import settings
from services.cache_service import CacheService, get_cache_service
from services.database_service import DatabaseService, get_database_service

logger = logging.getLogger(__name__)


class ToolArtifactService:
    """Stores tool artifacts with Redis hot-cache + Blob durability + SQL metadata."""

    def __init__(
        self,
        database_service: DatabaseService | None = None,
        cache_service: CacheService | None = None,
        blob_service: BlobServiceClient | None = None,
        container_name: str | None = None,
        cache_ttl_seconds: int | None = None,
        blob_prefix: str | None = None,
        cache_key_prefix: str | None = None,
    ):
        self.db = database_service or get_database_service()
        self.cache_service = cache_service

        if blob_service is not None:
            self.blob_service = blob_service
        elif settings.azure.storage_connection_string:
            self.blob_service = BlobServiceClient.from_connection_string(
                settings.azure.storage_connection_string
            )
        else:
            self.blob_service = None

        self.container_name = container_name or settings.azure.storage_container_name
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.artifacts.cache_ttl_seconds
        )
        self.blob_prefix = (blob_prefix or settings.artifacts.blob_prefix).strip("/")
        self.cache_key_prefix = cache_key_prefix or settings.artifacts.cache_key_prefix

    async def _get_cache_service(self) -> CacheService:
        if self.cache_service is None:
            self.cache_service = await get_cache_service()
        return self.cache_service

    def _cache_key(self, artifact_id: str) -> str:
        return f"{self.cache_key_prefix}:{artifact_id}"

    def _build_blob_name(self, session_id: str, tool_name: str, artifact_id: str) -> str:
        safe_session_id = (
            "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id) or "session"
        )
        safe_tool_name = (
            "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tool_name) or "tool"
        )
        date_partition = datetime.now(UTC).strftime("%Y%m%d")

        relative_name = f"{safe_session_id}/{date_partition}/{safe_tool_name}_{artifact_id}.json.gz"
        return f"{self.blob_prefix}/{relative_name}" if self.blob_prefix else relative_name

    async def _set_cached_payload(
        self,
        artifact_id: str,
        payload: dict[str, Any] | list[Any] | str | int | float | bool | None,
        checksum_sha256: str,
    ) -> None:
        cache = await self._get_cache_service()
        cache_payload = {
            "payload": payload,
            "checksum_sha256": checksum_sha256,
        }
        serialized = json.dumps(cache_payload, ensure_ascii=False).encode("utf-8")
        await cache._set_raw(self._cache_key(artifact_id), serialized, self.cache_ttl_seconds)

    async def _get_cached_payload(self, artifact_id: str) -> Any | None:
        cache = await self._get_cache_service()
        raw_data = await cache._get_raw(self._cache_key(artifact_id))
        if not raw_data:
            return None

        try:
            cached = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Cached artifact payload is invalid JSON: %s", artifact_id)
            return None

        if isinstance(cached, dict) and "payload" in cached:
            return cached["payload"]
        return cached

    async def _download_blob_bytes(self, blob_name: str) -> bytes:
        if self.blob_service is None:
            raise ValueError("Azure Blob Storage is not configured for tool artifacts")

        blob_client = self.blob_service.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )

        def _download() -> bytes:
            return blob_client.download_blob().readall()

        return await asyncio.to_thread(_download)

    async def save_artifact(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        session_id: str,
        payload: dict[str, Any] | list[Any] | str | int | float | bool | None,
        thread_id: str | None = None,
        user_id: str | None = None,
        media_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist full tool output and return artifact metadata."""
        if self.blob_service is None:
            raise ValueError("Azure Blob Storage is not configured for tool artifacts")

        artifact_id = str(uuid4())
        payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        compressed_payload = gzip.compress(payload_bytes)
        checksum_sha256 = hashlib.sha256(payload_bytes).hexdigest()

        blob_name = self._build_blob_name(session_id, tool_name, artifact_id)
        blob_client = self.blob_service.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )

        await asyncio.to_thread(
            blob_client.upload_blob,
            compressed_payload,
            overwrite=True,
            content_settings=ContentSettings(
                content_type="application/json",
                content_encoding="gzip",
            ),
        )

        artifact_data = {
            "id": artifact_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "session_id": session_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "media_id": media_id,
            "blob_name": blob_name,
            "content_type": "application/json",
            "content_encoding": "gzip",
            "size_bytes": len(payload_bytes),
            "compressed_size_bytes": len(compressed_payload),
            "checksum_sha256": checksum_sha256,
            "artifact_metadata": metadata or {},
        }

        artifact = await asyncio.to_thread(self.db.create_tool_artifact, artifact_data)
        await self._set_cached_payload(artifact.id, payload, checksum_sha256)
        return artifact.to_dict()

    async def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """Retrieve artifact payload with cache-first behavior."""
        artifact = await asyncio.to_thread(self.db.get_tool_artifact, artifact_id)
        if artifact is None:
            return None

        cached_payload = await self._get_cached_payload(artifact_id)
        if cached_payload is not None:
            await asyncio.to_thread(self.db.update_tool_artifact_accessed_at, artifact_id)
            response = artifact.to_dict()
            response["payload"] = cached_payload
            response["source"] = "cache"
            return response

        compressed_payload = await self._download_blob_bytes(artifact.blob_name)
        payload_bytes = (
            gzip.decompress(compressed_payload)
            if artifact.content_encoding == "gzip"
            else compressed_payload
        )

        computed_checksum = hashlib.sha256(payload_bytes).hexdigest()
        if computed_checksum != artifact.checksum_sha256:
            raise ValueError(f"Checksum mismatch for tool artifact {artifact_id}")

        payload = json.loads(payload_bytes.decode("utf-8"))
        await self._set_cached_payload(artifact_id, payload, artifact.checksum_sha256)
        await asyncio.to_thread(self.db.update_tool_artifact_accessed_at, artifact_id)

        response = artifact.to_dict()
        response["payload"] = payload
        response["source"] = "blob"
        return response


_tool_artifact_service: ToolArtifactService | None = None


async def get_tool_artifact_service() -> ToolArtifactService:
    """Get or create ToolArtifactService singleton."""
    global _tool_artifact_service
    if _tool_artifact_service is None:
        cache_service = await get_cache_service()
        _tool_artifact_service = ToolArtifactService(cache_service=cache_service)
    return _tool_artifact_service
