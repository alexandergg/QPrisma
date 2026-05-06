"""Service-layer upload orchestration for media routes."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from fastapi import HTTPException, UploadFile

from core.errors import bad_request, service_unavailable
from core.exceptions import internal_error

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}


@dataclass(frozen=True)
class OptimizedUploadOptions:
    """Options for the optimized video processing pipeline."""

    preset: str
    max_frames: int
    use_scene_detection: bool
    use_hierarchical_summary: bool
    scene_threshold: float
    max_scenes_per_chapter: int

    @property
    def pipeline_config(self) -> dict[str, Any]:
        return {
            "use_scene_detection": self.use_scene_detection,
            "use_hierarchical_summary": self.use_hierarchical_summary,
            "scene_threshold": self.scene_threshold,
            "max_scenes_per_chapter": self.max_scenes_per_chapter,
        }


class MediaUploadService:
    """Coordinates blob upload, media metadata creation, and video dispatch."""

    def __init__(
        self,
        *,
        blob_service: Any,
        db: Any,
        container_name: str,
        dispatch_service_factory: Callable[[], Any],
    ) -> None:
        self.blob_service = blob_service
        self.db = db
        self.container_name = container_name
        self.dispatch_service_factory = dispatch_service_factory

    async def upload_media(
        self,
        *,
        file: UploadFile,
        user_id: str,
        preset: str | None,
        max_frames: int | None,
    ) -> dict[str, Any]:
        """Upload an image or video and dispatch video processing when needed."""
        try:
            media_id = str(uuid.uuid4())
            file_extension = self._file_extension(file, default="bin")
            media_type = "video" if file_extension in VIDEO_EXTENSIONS else "image"
            blob_name = f"{media_id}.{file_extension}"

            file_size = await self._upload_blob(file=file, blob_name=blob_name)
            media_data = {
                "id": media_id,
                "user_id": user_id,
                "blob_name": blob_name,
                "original_filename": file.filename,
                "media_type": media_type,
                "file_size": file_size,
                "content_type": file.content_type,
                "processing_status": "queued" if media_type == "video" else "uploaded",
            }
            self.db.create_media(media_data)

            job_id = None
            dispatch_backend = None
            if media_type == "video":
                dispatch_result = await self._dispatch_video(
                    media_id=media_id,
                    blob_name=blob_name,
                    user_id=user_id,
                    file_size=file_size,
                    preset=preset,
                    max_frames=int(max_frames) if max_frames else None,
                    pipeline_config={},
                    optimized_pipeline=False,
                )
                job_id = dispatch_result.job_id
                dispatch_backend = dispatch_result.backend

            return {
                "media_id": media_id,
                "blob_name": blob_name,
                "media_type": media_type,
                "file_size": file_size,
                "job_id": job_id,
                "status": media_data.get("processing_status"),
                "message": "File uploaded. Processing queued." if job_id else "File uploaded.",
                "pipeline": dispatch_backend,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error uploading file: %s", e, exc_info=True)
            raise internal_error() from e

    async def upload_optimized_video(
        self,
        *,
        file: UploadFile,
        user_id: str,
        options: OptimizedUploadOptions,
    ) -> dict[str, Any]:
        """Upload a video and dispatch it to the optimized processing pipeline."""
        file_extension = self._file_extension(file, default="")
        if file_extension not in VIDEO_EXTENSIONS:
            raise bad_request("Only videos (mp4, avi, mov, mkv, webm)")

        try:
            media_id = str(uuid.uuid4())
            blob_name = f"{media_id}.{file_extension}"
            file_size = await self._upload_blob(file=file, blob_name=blob_name)
            logger.info("Uploaded optimized video size: %.2f MB", file_size / (1024 * 1024))

            pipeline_config = options.pipeline_config
            media_data = {
                "id": media_id,
                "user_id": user_id,
                "blob_name": blob_name,
                "original_filename": file.filename,
                "media_type": "video",
                "file_size": file_size,
                "content_type": file.content_type,
                "processing_status": "queued",
                "optimized_pipeline": True,
                "pipeline_config": pipeline_config,
            }
            self.db.create_media(media_data)

            dispatch_result = await self._dispatch_video(
                media_id=media_id,
                blob_name=blob_name,
                user_id=user_id,
                file_size=file_size,
                preset=options.preset,
                max_frames=min(options.max_frames, 500),
                pipeline_config=pipeline_config,
                optimized_pipeline=True,
            )

            return {
                "media_id": media_id,
                "blob_name": blob_name,
                "media_type": "video",
                "file_size": file_size,
                "job_id": dispatch_result.job_id,
                "status": "queued",
                "message": "Video uploaded. Processing queued.",
                "pipeline": dispatch_result.backend,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Upload error: %s", e, exc_info=True)
            raise internal_error() from e

    async def _upload_blob(self, *, file: UploadFile, blob_name: str) -> int:
        blob_client = self.blob_service.get_blob_client(
            container=self.container_name, blob=blob_name
        )
        file_size = file.size or 0
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(blob_client.upload_blob, file.file, overwrite=True, length=file_size or None),
        )

        if not file_size:
            props = await loop.run_in_executor(None, blob_client.get_blob_properties)
            file_size = props.size
        return file_size

    async def _dispatch_video(
        self,
        *,
        media_id: str,
        blob_name: str,
        user_id: str,
        file_size: int,
        preset: str | None,
        max_frames: int | None,
        pipeline_config: dict[str, Any],
        optimized_pipeline: bool,
    ) -> Any:
        try:
            dispatch_service = self.dispatch_service_factory()
            dispatch_result = await dispatch_service.dispatch_video(
                media_id=media_id,
                blob_name=blob_name,
                user_id=user_id,
                file_size=file_size,
                preset=preset,
                max_frames=max_frames,
                pipeline_config=pipeline_config,
                optimized_pipeline=optimized_pipeline,
            )
            self.db.update_media(media_id, dispatch_result.media_updates())
            return dispatch_result
        except Exception as e:
            logger.error("Processing dispatch failed for %s: %s", media_id, e, exc_info=True)
            self._mark_processing_dispatch_failed(media_id)
            raise service_unavailable("Task queue is unavailable") from e

    def _mark_processing_dispatch_failed(self, media_id: str) -> None:
        self.db.update_media(
            media_id,
            {
                "processing_status": "failed",
                "processing_message": "Processing dispatch failed before the job was queued.",
                "processing_progress": 0.0,
                "processed": False,
            },
        )

    @staticmethod
    def _file_extension(file: UploadFile, *, default: str) -> str:
        return file.filename.split(".")[-1].lower() if file.filename else default
