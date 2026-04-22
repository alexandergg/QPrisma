"""Tests for benchmark automation routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.dependencies as deps
from api.dependencies import require_benchmark_operator
from models.benchmark_schemas import BenchmarkStatusItem


@pytest.mark.unit
class TestBenchmarkRoutes:
    def test_requires_benchmark_auth(self, client):
        resp = client.get("/benchmark/status", params={"benchmark_name": "video_mme"})
        assert resp.status_code == 401

    def test_status_accepts_benchmark_token(self, client):
        mock_service = MagicMock()
        mock_service.list_status.return_value = [
            BenchmarkStatusItem(
                benchmark_name="video_mme",
                benchmark_video_id="video_001",
                benchmark_split="short",
                user_id="user_7541242e88e3",
                media_id="media_123",
                blob_name="media_123.mp4",
                job_id="job_123",
                processing_status="completed",
                processed=True,
                last_updated="2026-04-21T00:00:00+00:00",
            )
        ]

        with (
            patch.object(deps.settings.benchmark, "api_token", "secret-token"),
            patch(
                "api.routes.benchmark_routes.get_benchmark_ingest_service",
                return_value=mock_service,
            ),
        ):
            resp = client.get(
                "/benchmark/status",
                params={"benchmark_name": "video_mme"},
                headers={"X-Benchmark-Token": "secret-token"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "user_7541242e88e3"
        assert body["completed"] == 1
        assert body["items"][0]["benchmark_video_id"] == "video_001"

    def test_status_uses_default_user_id_for_empty_results(self, app):
        app.dependency_overrides[require_benchmark_operator] = lambda: None
        mock_service = MagicMock()
        mock_service.list_status.return_value = []

        from fastapi.testclient import TestClient

        with (
            patch(
                "api.routes.benchmark_routes.get_benchmark_ingest_service",
                return_value=mock_service,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.get(
                "/benchmark/status",
                params={"benchmark_name": "video_mme"},
            )

        assert resp.status_code == 200
        assert resp.json()["user_id"] == "user_7541242e88e3"

    def test_ingest_batch_success(self, app):
        app.dependency_overrides[require_benchmark_operator] = lambda: None
        mock_service = MagicMock()
        mock_service.ingest_video = AsyncMock(
            side_effect=[
                {
                    "benchmark_name": "video_mme",
                    "benchmark_video_id": "video_001",
                    "benchmark_split": "short",
                    "user_id": "user_7541242e88e3",
                    "media_id": "media_001",
                    "blob_name": "media_001.mp4",
                    "source_blob_name": "video_001.mp4",
                    "job_id": "job_001",
                    "processing_status": "queued",
                    "ingest_status": "queued",
                },
                {
                    "benchmark_name": "video_mme",
                    "benchmark_video_id": "video_002",
                    "benchmark_split": "medium",
                    "user_id": "user_7541242e88e3",
                    "media_id": "media_002",
                    "blob_name": "media_002.mp4",
                    "source_blob_name": "video_002.mp4",
                    "job_id": "job_002",
                    "processing_status": "queued",
                    "ingest_status": "queued",
                },
            ]
        )

        from fastapi.testclient import TestClient

        with (
            patch(
                "api.routes.benchmark_routes.get_benchmark_ingest_service",
                return_value=mock_service,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/benchmark/ingest/batch",
                json={
                    "videos": [
                        {
                            "benchmark_name": "video_mme",
                            "benchmark_video_id": "video_001",
                            "source_container": "benchmarks",
                            "source_blob_name": "video_001.mp4",
                            "benchmark_split": "short",
                        },
                        {
                            "benchmark_name": "video_mme",
                            "benchmark_video_id": "video_002",
                            "source_container": "benchmarks",
                            "source_blob_name": "video_002.mp4",
                            "benchmark_split": "medium",
                        },
                    ]
                },
            )

        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_ingest_batch_returns_internal_error_for_unexpected_exception(self, app):
        app.dependency_overrides[require_benchmark_operator] = lambda: None
        mock_service = MagicMock()
        mock_service.ingest_video = AsyncMock(side_effect=Exception("boom"))

        from fastapi.testclient import TestClient

        with (
            patch(
                "api.routes.benchmark_routes.get_benchmark_ingest_service",
                return_value=mock_service,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/benchmark/ingest/batch",
                json={
                    "videos": [
                        {
                            "benchmark_name": "video_mme",
                            "benchmark_video_id": "video_001",
                            "source_container": "benchmarks",
                            "source_blob_name": "video_001.mp4",
                        }
                    ]
                },
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Benchmark ingest failed"

    def test_manifest_success(self, app):
        app.dependency_overrides[require_benchmark_operator] = lambda: None
        mock_service = MagicMock()
        mock_service.build_manifest.return_value = {
            "name": "video_mme",
            "user_id": "user_7541242e88e3",
            "videos": [{"benchmark_video_id": "video_001", "media_id": "media_001"}],
        }

        from fastapi.testclient import TestClient

        with (
            patch(
                "api.routes.benchmark_routes.get_benchmark_ingest_service",
                return_value=mock_service,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/benchmark/manifest",
                json={"benchmark_name": "video_mme"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["video_count"] == 1
        assert body["manifest"]["name"] == "video_mme"
