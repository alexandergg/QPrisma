"""Tests for benchmark_ingest_service.py."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from sqlalchemy.exc import IntegrityError

from models.benchmark_schemas import BenchmarkIngestRequest, BenchmarkManifestRequest


@pytest.mark.unit
async def test_ingest_video_returns_existing_row_without_copy():
    existing = MagicMock()
    existing.id = "media_existing"
    existing.blob_name = "media_existing.mp4"
    existing.job_id = "job_existing"
    existing.processing_status = "completed"
    existing.benchmark_split = "short"

    mock_db = MagicMock()
    mock_db.get_media_by_benchmark_key.return_value = existing
    mock_blob = MagicMock()

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
    ):
        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        result = await service.ingest_video(
            BenchmarkIngestRequest(
                benchmark_name="video_mme",
                benchmark_video_id="video_001",
                source_container="benchmarks",
                source_blob_name="video_001.mp4",
            )
        )

    assert result.ingest_status == "skipped_existing"
    assert result.media_id == "media_existing"
    mock_blob.get_blob_client.assert_not_called()


@pytest.mark.unit
async def test_ingest_video_copies_blob_and_dispatches_job():
    mock_db = MagicMock()
    mock_db.get_media_by_benchmark_key.return_value = None
    mock_blob = MagicMock()

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
        patch("tasks.video_tasks.process_video_pipeline.apply_async") as mock_apply_async,
    ):
        mock_apply_async.return_value = MagicMock(id="job_123")

        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        service._copy_source_blob = MagicMock(return_value=(1024, "video/mp4"))

        result = await service.ingest_video(
            BenchmarkIngestRequest(
                benchmark_name="video_mme",
                benchmark_video_id="video_001",
                source_container="benchmarks",
                source_blob_name="video_001.mp4",
                benchmark_split="short",
            )
        )

    assert result.ingest_status == "queued"
    assert result.job_id == "job_123"
    mock_db.create_media.assert_called_once()
    mock_db.update_media.assert_called_once()


@pytest.mark.unit
async def test_ingest_video_returns_existing_row_after_concurrent_duplicate_insert():
    existing = MagicMock()
    existing.id = "media_existing"
    existing.blob_name = "media_existing.mp4"
    existing.job_id = "job_existing"
    existing.processing_status = "queued"
    existing.benchmark_split = "short"

    mock_db = MagicMock()
    mock_db.get_media_by_benchmark_key.side_effect = [None, existing]
    mock_db.create_media.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    mock_blob = MagicMock()

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
        patch("tasks.video_tasks.process_video_pipeline.apply_async") as mock_apply_async,
    ):
        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        service._copy_source_blob = MagicMock(return_value=(1024, "video/mp4"))

        result = await service.ingest_video(
            BenchmarkIngestRequest(
                benchmark_name="video_mme",
                benchmark_video_id="video_001",
                source_container="benchmarks",
                source_blob_name="video_001.mp4",
                benchmark_split="short",
            )
        )

    assert result.ingest_status == "skipped_existing"
    assert result.media_id == "media_existing"
    mock_apply_async.assert_not_called()
    mock_blob.get_blob_client.return_value.delete_blob.assert_called_once_with(
        delete_snapshots="include"
    )


@pytest.mark.unit
async def test_ingest_video_avoids_logging_user_values_for_duplicate_requests():
    existing = MagicMock()
    existing.id = "media_existing"
    existing.blob_name = "media_existing.mp4"
    existing.job_id = "job_existing"
    existing.processing_status = "queued"
    existing.benchmark_split = "short"

    mock_db = MagicMock()
    mock_db.get_media_by_benchmark_key.side_effect = [None, existing]
    mock_db.create_media.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    mock_blob = MagicMock()

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
        patch("services.benchmark_ingest_service.logger") as mock_logger,
    ):
        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        service._copy_source_blob = MagicMock(return_value=(1024, "video/mp4"))

        await service.ingest_video(
            BenchmarkIngestRequest(
                benchmark_name="video\nmme",
                benchmark_video_id="video_001\r\nbad",
                source_container="benchmarks",
                source_blob_name="video_001.mp4",
                benchmark_split="short",
            )
        )

    mock_logger.info.assert_called_once_with(
        "Benchmark ingest deduplicated concurrent request while creating media_id %s",
        ANY,
    )


@pytest.mark.unit
def test_delete_target_blob_omits_blob_name_from_warning_log():
    mock_db = MagicMock()
    mock_blob = MagicMock()
    mock_blob.get_blob_client.return_value.delete_blob.side_effect = AzureError("boom")

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
        patch("services.benchmark_ingest_service.logger") as mock_logger,
    ):
        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        service._delete_target_blob("duplicate\nblob.mp4")

    mock_logger.warning.assert_called_once_with(
        "Failed to delete duplicate benchmark blob during dedup cleanup",
        exc_info=True,
    )


@pytest.mark.unit
def test_build_manifest_uses_benchmark_rows():
    row = MagicMock()
    row.benchmark_name = "video_mme"
    row.benchmark_video_id = "video_001"
    row.benchmark_split = "short"
    row.user_id = "user_7541242e88e3"
    row.id = "media_001"
    row.blob_name = "media_001.mp4"
    row.job_id = "job_001"
    row.processing_status = "completed"
    row.processed = True
    row.last_updated = datetime(2026, 4, 21, tzinfo=UTC)

    mock_db = MagicMock()
    mock_db.get_media_by_benchmark.return_value = [row]
    mock_blob = MagicMock()

    with (
        patch("services.benchmark_ingest_service.get_database_service", return_value=mock_db),
        patch("services.benchmark_ingest_service.get_blob_service", return_value=mock_blob),
        patch("services.benchmark_ingest_service.get_storage_container_name", return_value="media"),
    ):
        from services.benchmark_ingest_service import BenchmarkIngestService

        service = BenchmarkIngestService()
        manifest = service.build_manifest(BenchmarkManifestRequest(benchmark_name="video_mme"))

    assert manifest["name"] == "video_mme"
    assert manifest["videos"][0]["benchmark_video_id"] == "video_001"
    assert manifest["dataset_hash"].startswith("sha256:")
