"""Service layer for benchmark ingestion from Blob-hosted source datasets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import BlobSasPermissions
from sqlalchemy.exc import IntegrityError

from api.dependencies import (
    build_blob_sas_url,
    get_blob_service,
    get_storage_container_name,
)
from core.config import settings
from models.benchmark_schemas import (
    BenchmarkIngestRequest,
    BenchmarkIngestResponse,
    BenchmarkManifestRequest,
    BenchmarkStatusItem,
)
from services.database_service import get_database_service

logger = logging.getLogger(__name__)

VALID_VIDEO_EXTS = {"mp4", "avi", "mov", "mkv", "webm"}
BENCHMARK_COPY_TIMEOUT_S = 15 * 60
_LOG_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

_benchmark_ingest_service: BenchmarkIngestService | None = None


def _normalize_benchmark_name(name: str) -> str:
    return name.strip().lower()


def _sanitize_log_value(value: object, max_len: int = 200) -> str:
    """Strip control characters and truncate user-influenced log values."""
    return _LOG_CONTROL_CHARS_RE.sub("", str(value))[:max_len]


def _dataset_hash(items: Sequence[BenchmarkStatusItem]) -> str:
    payload = json.dumps(
        sorted(
            (
                {
                    "benchmark_video_id": item.benchmark_video_id,
                    "media_id": item.media_id,
                    "duration_bucket": item.benchmark_split,
                }
                for item in items
            ),
            key=lambda row: row["benchmark_video_id"],
        ),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BenchmarkIngestService:
    """Coordinate Blob copy + media row creation + Celery dispatch for benchmark media."""

    def __init__(self) -> None:
        self._db = get_database_service()
        self._blob_service = get_blob_service()
        self._target_container = get_storage_container_name()

    async def ingest_video(self, request: BenchmarkIngestRequest) -> BenchmarkIngestResponse:
        """Ingest one benchmark video from a source blob."""
        if self._db is None:
            raise RuntimeError("Database service is not configured")
        if self._blob_service is None:
            raise RuntimeError("Azure Blob Storage is not configured")

        benchmark_name = _normalize_benchmark_name(request.benchmark_name)
        user_id = request.user_id or settings.benchmark.default_user_id
        existing = self._db.get_media_by_benchmark_key(
            user_id,
            benchmark_name,
            request.benchmark_video_id,
        )
        if existing:
            return self._build_existing_response(
                request=request,
                existing=existing,
                benchmark_name=benchmark_name,
                user_id=user_id,
            )

        ext = Path(request.source_blob_name).suffix.lstrip(".").lower() or "mp4"
        if ext not in VALID_VIDEO_EXTS:
            raise ValueError(f"Unsupported video extension: {ext}")

        media_id = str(uuid.uuid4())
        destination_blob_name = f"{media_id}.{ext}"
        file_size, content_type = await asyncio.to_thread(
            self._copy_source_blob,
            request.source_container,
            request.source_blob_name,
            destination_blob_name,
            request.content_type,
        )

        media_data = {
            "id": media_id,
            "user_id": user_id,
            "blob_name": destination_blob_name,
            "original_filename": request.original_filename or Path(request.source_blob_name).name,
            "media_type": "video",
            "file_size": file_size,
            "content_type": content_type or f"video/{ext}",
            "processing_status": "queued",
            "benchmark_name": benchmark_name,
            "benchmark_video_id": request.benchmark_video_id,
            "benchmark_split": request.benchmark_split,
        }
        try:
            self._db.create_media(media_data)
        except IntegrityError:
            self._delete_target_blob(destination_blob_name)
            existing = self._db.get_media_by_benchmark_key(
                user_id,
                benchmark_name,
                request.benchmark_video_id,
            )
            if existing:
                logger.info(
                    "Benchmark ingest deduplicated concurrent request for %s/%s",
                    _sanitize_log_value(benchmark_name),
                    _sanitize_log_value(request.benchmark_video_id),
                )
                return self._build_existing_response(
                    request=request,
                    existing=existing,
                    benchmark_name=benchmark_name,
                    user_id=user_id,
                )
            raise

        from tasks.video_tasks import process_video_pipeline

        celery_config = {
            "max_frames": request.max_frames,
            "custom_prompt": None,
            "index_graph": True,
            "preset": request.preset,
        }
        async_result = process_video_pipeline.apply_async(
            args=[media_id, destination_blob_name, celery_config]
        )
        self._db.update_media(media_id, {"job_id": async_result.id})

        return BenchmarkIngestResponse(
            benchmark_name=benchmark_name,
            benchmark_video_id=request.benchmark_video_id,
            benchmark_split=request.benchmark_split,
            user_id=user_id,
            media_id=media_id,
            blob_name=destination_blob_name,
            source_blob_name=request.source_blob_name,
            job_id=async_result.id,
            processing_status="queued",
            ingest_status="queued",
        )

    def list_status(
        self,
        *,
        benchmark_name: str,
        user_id: str | None,
        benchmark_video_ids: list[str] | None = None,
        media_ids: list[str] | None = None,
    ) -> list[BenchmarkStatusItem]:
        """Return benchmark processing status rows."""
        if self._db is None:
            raise RuntimeError("Database service is not configured")

        resolved_user_id = user_id or settings.benchmark.default_user_id
        rows = self._db.get_media_by_benchmark(
            resolved_user_id,
            _normalize_benchmark_name(benchmark_name),
            benchmark_video_ids=benchmark_video_ids,
            media_ids=media_ids,
        )
        return [
            BenchmarkStatusItem(
                benchmark_name=row.benchmark_name or benchmark_name,
                benchmark_video_id=row.benchmark_video_id or "",
                benchmark_split=row.benchmark_split,
                user_id=row.user_id,
                media_id=row.id,
                blob_name=row.blob_name,
                job_id=row.job_id,
                processing_status=row.processing_status,
                processed=bool(row.processed),
                last_updated=row.last_updated.isoformat() if row.last_updated else None,
            )
            for row in rows
            if row.benchmark_video_id
        ]

    def build_manifest(self, request: BenchmarkManifestRequest) -> dict[str, Any]:
        """Build a BenchmarkManifest payload from stored benchmark rows."""
        from evaluation_foundry.benchmarks import BenchmarkManifest, BenchmarkVideo

        status_items = self.list_status(
            benchmark_name=request.benchmark_name,
            user_id=request.user_id,
            benchmark_video_ids=request.benchmark_video_ids,
            media_ids=request.media_ids,
        )
        if not status_items:
            raise ValueError("No benchmark media rows found for manifest generation")

        resolved_user_id = request.user_id or settings.benchmark.default_user_id
        manifest = BenchmarkManifest(
            name=_normalize_benchmark_name(request.benchmark_name),
            version=request.version,
            license=request.license,
            user_id=resolved_user_id,
            eval_mode=request.eval_mode,
            format=request.response_format,
            judge_model=request.judge_model,
            n_judge_runs=request.n_judge_runs,
            judge_temperature=request.judge_temperature,
            frame_sampling_fps=request.frame_sampling_fps,
            max_frames=request.max_frames,
            subtitle_mode=request.subtitle_mode,
            agent_commit_sha=request.agent_commit_sha,
            dataset_hash=_dataset_hash(status_items),
            videos=[
                BenchmarkVideo(
                    benchmark_video_id=item.benchmark_video_id,
                    media_id=item.media_id,
                    duration_bucket=item.benchmark_split,
                    extra={"status": item.processing_status, "job_id": item.job_id},
                )
                for item in status_items
            ],
        )
        return manifest.to_dict()

    def _copy_source_blob(
        self,
        source_container: str,
        source_blob_name: str,
        destination_blob_name: str,
        requested_content_type: str | None,
    ) -> tuple[int | None, str | None]:
        """Server-side copy the source blob into the app media container and wait for completion."""
        if self._blob_service is None:
            raise RuntimeError("Azure Blob Storage is not configured")

        source_client = self._blob_service.get_blob_client(
            container=source_container,
            blob=source_blob_name,
        )
        try:
            source_props = source_client.get_blob_properties()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(
                f"Source blob not found: {source_container}/{source_blob_name}"
            ) from exc

        source_url = build_blob_sas_url(
            source_blob_name,
            container_name=source_container,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(UTC) + timedelta(hours=1),
        )
        if not source_url:
            raise RuntimeError("Could not generate SAS URL for benchmark source blob")

        destination_client = self._blob_service.get_blob_client(
            container=self._target_container,
            blob=destination_blob_name,
        )
        destination_client.start_copy_from_url(source_url)

        deadline = datetime.now(UTC) + timedelta(seconds=BENCHMARK_COPY_TIMEOUT_S)
        while datetime.now(UTC) < deadline:
            props = destination_client.get_blob_properties()
            copy_info = getattr(props, "copy", None)
            copy_status = getattr(copy_info, "status", None)
            if copy_status == "success":
                resolved_size = getattr(props, "size", None) or getattr(source_props, "size", None)
                resolved_content_type = (
                    requested_content_type
                    or getattr(getattr(props, "content_settings", None), "content_type", None)
                    or getattr(
                        getattr(source_props, "content_settings", None), "content_type", None
                    )
                )
                return resolved_size, resolved_content_type
            if copy_status == "failed":
                description = getattr(copy_info, "status_description", "unknown copy failure")
                raise RuntimeError(f"Blob copy failed: {description}")
            import time

            time.sleep(1)

        try:
            props = destination_client.get_blob_properties()
            copy_info = getattr(props, "copy", None)
            if copy_info and getattr(copy_info, "id", None):
                destination_client.abort_copy(copy_info.id)
        except AzureError:
            logger.warning("Failed to abort timed-out benchmark blob copy", exc_info=True)
        raise TimeoutError(
            f"Timed out waiting for copy of {source_container}/{source_blob_name} to {destination_blob_name}"
        )

    def _build_existing_response(
        self,
        *,
        request: BenchmarkIngestRequest,
        existing: Any,
        benchmark_name: str,
        user_id: str,
    ) -> BenchmarkIngestResponse:
        """Build a consistent response for an existing benchmark media row."""
        return BenchmarkIngestResponse(
            benchmark_name=benchmark_name,
            benchmark_video_id=request.benchmark_video_id,
            benchmark_split=existing.benchmark_split,
            user_id=user_id,
            media_id=existing.id,
            blob_name=existing.blob_name,
            source_blob_name=request.source_blob_name,
            job_id=existing.job_id,
            processing_status=existing.processing_status,
            ingest_status="skipped_existing",
        )

    def _delete_target_blob(self, blob_name: str) -> None:
        """Best-effort cleanup for a copied blob that lost a duplicate insert race."""
        if self._blob_service is None:
            return

        try:
            self._blob_service.get_blob_client(
                container=self._target_container,
                blob=blob_name,
            ).delete_blob(delete_snapshots="include")
        except AzureError:
            logger.warning(
                "Failed to delete duplicate benchmark blob %s",
                _sanitize_log_value(blob_name),
                exc_info=True,
            )


def get_benchmark_ingest_service() -> BenchmarkIngestService:
    """Get or create the benchmark ingest service singleton."""
    global _benchmark_ingest_service
    if _benchmark_ingest_service is None:
        _benchmark_ingest_service = BenchmarkIngestService()
    return _benchmark_ingest_service
