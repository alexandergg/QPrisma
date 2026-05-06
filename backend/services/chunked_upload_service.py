"""Service-layer orchestration for chunked media uploads."""

import base64
import binascii
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from azure.storage.blob import BlobBlock, BlobSasPermissions
from fastapi import HTTPException

from core.degraded import DegradationImpact, record_degraded_operation

logger = logging.getLogger(__name__)

DEFAULT_BLOCK_SIZE_MB = 8
MAX_BLOCK_SIZE_MB = 100
MAX_BLOCKS = 50000
MAX_FILE_SIZE_GB = 190


def generate_block_id(index: int) -> str:
    """Generate a base64 Azure Blob Storage block ID with stable sorting."""
    block_id = f"{index:06d}-{uuid.uuid4().hex[:8]}"
    return base64.b64encode(block_id.encode()).decode()


class ChunkedUploadService:
    """Coordinates chunked upload sessions, blob commits, and processing dispatch."""

    def __init__(
        self,
        *,
        blob_service: Any | None,
        db: Any,
        container_name: str,
        sas_url_builder: Callable[..., Awaitable[str | None]],
        dispatch_service_factory: Callable[[], Any],
    ) -> None:
        self.blob_service = blob_service
        self.db = db
        self.container_name = container_name
        self.sas_url_builder = sas_url_builder
        self.dispatch_service_factory = dispatch_service_factory

    async def init_upload(
        self,
        *,
        filename: str,
        file_size: int,
        content_type: str,
        block_size_mb: int,
        user_id: str,
    ) -> dict[str, Any]:
        """Initialize a resumable block upload and persist its upload session."""
        self._require_blob_service()

        max_size = MAX_FILE_SIZE_GB * 1024 * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(
                status_code=400, detail=f"File too large. Maximum size is {MAX_FILE_SIZE_GB}GB"
            )

        block_size_bytes = min(max(block_size_mb, 1), MAX_BLOCK_SIZE_MB) * 1024 * 1024
        total_blocks = (file_size + block_size_bytes - 1) // block_size_bytes
        if total_blocks > MAX_BLOCKS:
            block_size_bytes = (file_size + MAX_BLOCKS - 1) // MAX_BLOCKS
            total_blocks = (file_size + block_size_bytes - 1) // block_size_bytes

        upload_id = str(uuid.uuid4())
        media_id = str(uuid.uuid4())
        file_extension = filename.split(".")[-1].lower() if "." in filename else "mp4"
        blob_name = f"{media_id}.{file_extension}"
        blocks = [
            {
                "block_id": generate_block_id(i),
                "block_index": i,
            }
            for i in range(total_blocks)
        ]

        sas_expiry = datetime.now(UTC) + timedelta(hours=4)
        upload_url = await self.sas_url_builder(
            blob_name,
            permission=BlobSasPermissions(write=True, create=True, read=True),
            expiry=sas_expiry,
        )
        if not upload_url:
            raise HTTPException(status_code=503, detail="Cannot generate SAS token")

        try:
            self.db.create_media(
                {
                    "id": media_id,
                    "user_id": user_id,
                    "blob_name": blob_name,
                    "original_filename": filename,
                    "media_type": "video",
                    "file_size": file_size,
                    "content_type": content_type,
                    "processing_status": "uploading",
                    "upload_session": {
                        "upload_id": upload_id,
                        "total_blocks": total_blocks,
                        "block_size": block_size_bytes,
                        "blocks": blocks,
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                }
            )
        except Exception as e:
            logger.error("Failed to create media record: %s", e)
            raise HTTPException(status_code=500, detail="Failed to initialize upload") from e

        logger.info(
            "Initialized chunked upload: %s, file=%s, size=%s, blocks=%s, block_size=%s",
            upload_id,
            filename,
            file_size,
            total_blocks,
            block_size_bytes,
        )

        return {
            "upload_id": upload_id,
            "media_id": media_id,
            "blob_name": blob_name,
            "block_size": block_size_bytes,
            "total_blocks": total_blocks,
            "upload_url": upload_url,
            "sas_expiry": sas_expiry.isoformat(),
            "blocks": blocks,
        }

    async def commit_upload(
        self,
        *,
        media_id: str,
        blob_name: str,
        block_ids: list[str],
        preset: str,
        max_frames: int,
        use_scene_detection: bool,
        use_hierarchical_summary: bool,
        user_id: str,
    ) -> dict[str, Any]:
        """Commit uploaded blocks, clear the upload session, and queue processing."""
        blob_service = self._require_blob_service()
        self._require_media_owner(media_id, user_id, missing_detail="Upload session not found")
        decoded_ids = self._decode_block_ids(block_ids)

        try:
            blob_client = blob_service.get_blob_client(
                container=self.container_name,
                blob=blob_name,
            )
            blob_client.commit_block_list(
                block_list=[BlobBlock(block_id=bid) for bid in decoded_ids],
            )
            final_size = blob_client.get_blob_properties().size
            logger.info("Committed blob: %s, blocks=%s, size=%s", blob_name, len(block_ids), final_size)
        except Exception as e:
            logger.error("Failed to commit blob: %s", e, exc_info=True)
            self.db.update_media(media_id, {"processing_status": "error"})
            raise HTTPException(status_code=500, detail="Storage operation failed") from e

        pipeline_config = {
            "use_scene_detection": use_scene_detection,
            "use_hierarchical_summary": use_hierarchical_summary,
        }
        self.db.update_media(
            media_id,
            {
                "file_size": final_size,
                "processing_status": "queued",
                "optimized_pipeline": True,
                "pipeline_config": pipeline_config,
                "upload_session": None,
            },
        )

        job_id = None
        dispatch_backend = None
        try:
            dispatch_service = self.dispatch_service_factory()
            dispatch_result = await dispatch_service.dispatch_video(
                media_id=media_id,
                blob_name=blob_name,
                user_id=user_id,
                file_size=final_size,
                preset=preset,
                max_frames=min(max_frames, 500),
                pipeline_config=pipeline_config,
                optimized_pipeline=True,
            )
            job_id = dispatch_result.job_id
            dispatch_backend = dispatch_result.backend
            self.db.update_media(media_id, dispatch_result.media_updates())
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="chunked_upload",
                operation="commit_processing_dispatch",
                impact=DegradationImpact.OPTIONAL_DISPATCH,
                exc=exc,
            )

        return {
            "media_id": media_id,
            "blob_name": blob_name,
            "file_size": final_size,
            "job_id": job_id,
            "status": "queued" if job_id else "uploaded",
            "message": (
                f"Upload complete. Processing queued via {dispatch_backend}."
                if job_id and dispatch_backend
                else "Upload complete."
            ),
        }

    def get_status(self, *, media_id: str, user_id: str) -> dict[str, Any]:
        """Return resumable upload status and uncommitted block progress."""
        media = self._require_media_owner(media_id, user_id, missing_detail="Upload not found")
        upload_session = media.upload_session if hasattr(media, "upload_session") else None

        if not upload_session:
            return {
                "media_id": media_id,
                "status": media.processing_status,
                "message": "Upload already completed or not using chunked upload",
            }

        uploaded_block_ids = set()
        if self.blob_service:
            blob_client = self.blob_service.get_blob_client(
                container=self.container_name,
                blob=media.blob_name,
            )
            try:
                block_list = blob_client.get_block_list(block_list_type="uncommitted")
                uploaded_block_ids = {block.id for block in block_list.uncommitted_blocks}
            except Exception:
                uploaded_block_ids = set()

        return {
            "media_id": media_id,
            "upload_id": upload_session.get("upload_id"),
            "status": "uploading",
            "total_blocks": upload_session.get("total_blocks"),
            "uploaded_blocks": len(uploaded_block_ids),
            "uploaded_block_ids": list(uploaded_block_ids),
            "remaining_blocks": [
                b for b in upload_session.get("blocks", []) if b["block_id"] not in uploaded_block_ids
            ],
        }

    def cancel_upload(self, *, media_id: str, user_id: str) -> dict[str, str]:
        """Cancel an in-progress upload and remove its media record."""
        media = self._require_media_owner(media_id, user_id, missing_detail="Upload not found")
        if self.blob_service:
            with suppress(Exception):
                blob_client = self.blob_service.get_blob_client(
                    container=self.container_name,
                    blob=media.blob_name,
                )
                blob_client.delete_blob()

        self.db.delete_media(media_id)
        return {"message": "Upload cancelled", "media_id": media_id}

    def _require_blob_service(self) -> Any:
        if not self.blob_service:
            raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")
        return self.blob_service

    def _require_media_owner(self, media_id: str, user_id: str, *, missing_detail: str) -> Any:
        media = self.db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail=missing_detail)
        if media.user_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return media

    @staticmethod
    def _decode_block_ids(block_ids: list[str]) -> list[str]:
        try:
            for block_id in block_ids:
                if len(block_id) % 4 != 0:
                    raise binascii.Error(f"incorrect padding for block ID: {block_id!r}")
            return [base64.b64decode(block_id, validate=True).decode() for block_id in block_ids]
        except (binascii.Error, UnicodeDecodeError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 block ID: {e}",
            ) from e
