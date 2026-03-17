"""Tests for video preparation service."""

import json

import httpx
import pytest
import respx

from evaluation.services.video_preparation import (
    VideoPreparationService,
    _sanitize_filename,
)


@pytest.fixture
def api_url():
    return "https://test-api.example.com"


@pytest.fixture
def tmp_video_dir(tmp_path):
    return tmp_path / "videos"


@pytest.fixture
def tmp_mapping_path(tmp_path):
    return tmp_path / "mapping.json"


class TestSanitizeFilename:
    def test_normal_id(self):
        assert _sanitize_filename("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_id_with_hyphens(self):
        assert _sanitize_filename("abc-def-123") == "abc-def-123"

    def test_id_with_special_chars(self):
        assert _sanitize_filename("ab/cd?ef") == "ab_cd_ef"


class TestDiscoverIndexedVideos:
    @respx.mock
    @pytest.mark.asyncio
    async def test_discovers_vmme_videos(self, api_url, tmp_video_dir, tmp_mapping_path):
        respx.get(f"{api_url}/media").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 2,
                    "media": [
                        {
                            "id": "uuid-111",
                            "original_filename": "vmme_dQw4w9WgXcQ.mp4",
                            "processing_status": "completed",
                        },
                        {
                            "id": "uuid-222",
                            "original_filename": "vmme_oHg5SJYRHA0.mp4",
                            "processing_status": "completed",
                        },
                        {
                            "id": "uuid-333",
                            "original_filename": "other_video.mp4",
                            "processing_status": "completed",
                        },
                    ],
                    "limit": 100,
                    "offset": 0,
                },
            )
        )

        async with VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        ) as svc:
            mapping = await svc.discover_indexed_videos()

        assert mapping == {
            "dQw4w9WgXcQ": "uuid-111",
            "oHg5SJYRHA0": "uuid-222",
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_skips_non_completed_videos(self, api_url, tmp_video_dir, tmp_mapping_path):
        respx.get(f"{api_url}/media").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "media": [
                        {
                            "id": "uuid-111",
                            "original_filename": "vmme_abc123.mp4",
                            "processing_status": "processing",
                        },
                    ],
                    "limit": 100,
                    "offset": 0,
                },
            )
        )

        async with VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        ) as svc:
            mapping = await svc.discover_indexed_videos()

        assert mapping == {}


class TestUploadVideos:
    @respx.mock
    @pytest.mark.asyncio
    async def test_upload_success(self, api_url, tmp_video_dir, tmp_mapping_path):
        # Create a dummy video file
        tmp_video_dir.mkdir(parents=True, exist_ok=True)
        video_path = tmp_video_dir / "vmme_abc123.mp4"
        video_path.write_bytes(b"fake video data")

        respx.post(f"{api_url}/upload").mock(
            return_value=httpx.Response(
                200,
                json={
                    "media_id": "new-uuid-456",
                    "blob_name": "vmme_abc123.mp4",
                    "status": "queued",
                },
            )
        )

        async with VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        ) as svc:
            mapping = await svc.upload_videos({"abc123": video_path})

        assert mapping == {"abc123": "new-uuid-456"}


class TestWaitForProcessing:
    @respx.mock
    @pytest.mark.asyncio
    async def test_wait_completed(self, api_url, tmp_video_dir, tmp_mapping_path):
        respx.get(f"{api_url}/media/uuid-1/status").mock(
            return_value=httpx.Response(200, json={"processing_status": "completed"})
        )

        async with VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        ) as svc:
            completed = await svc.wait_for_processing({"yt1": "uuid-1"})

        assert completed == {"yt1": "uuid-1"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_wait_failed(self, api_url, tmp_video_dir, tmp_mapping_path):
        respx.get(f"{api_url}/media/uuid-1/status").mock(
            return_value=httpx.Response(
                200, json={"processing_status": "failed", "error": "codec error"}
            )
        )

        async with VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        ) as svc:
            completed = await svc.wait_for_processing({"yt1": "uuid-1"})

        assert completed == {}


class TestBuildAndPersistMapping:
    def test_creates_mapping_file(self, api_url, tmp_video_dir, tmp_mapping_path):
        svc = VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        )

        result = svc.build_and_persist_mapping({"yt1": "uuid-1", "yt2": "uuid-2"})

        assert tmp_mapping_path.exists()
        saved = json.loads(tmp_mapping_path.read_text())
        assert saved == {"yt1": "uuid-1", "yt2": "uuid-2"}
        assert result == saved

    def test_merges_with_existing(self, api_url, tmp_video_dir, tmp_mapping_path):
        tmp_mapping_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_mapping_path.write_text(json.dumps({"old_yt": "old-uuid"}))

        svc = VideoPreparationService(
            api_url=api_url,
            token="test-token",
            video_dir=str(tmp_video_dir),
            mapping_path=str(tmp_mapping_path),
        )

        result = svc.build_and_persist_mapping({"new_yt": "new-uuid"})

        assert result == {"old_yt": "old-uuid", "new_yt": "new-uuid"}


class TestOrchestratorCLI:
    """Test CLI argument parsing for the orchestrator."""

    def test_parse_args_defaults(self):
        from evaluation.run_video_mme_eval import parse_args

        args = parse_args(
            ["--api-url", "https://test.com", "--email", "a@b.com", "--password", "p"]
        )
        assert args.api_url == "https://test.com"
        assert args.subset == "short"
        assert args.max_videos == 12
        assert args.skip_upload is False
        assert args.fresh is False
        assert args.concurrency == 3

    def test_parse_args_custom(self):
        from evaluation.run_video_mme_eval import parse_args

        args = parse_args(
            [
                "--api-url",
                "https://test.com",
                "--email",
                "a@b.com",
                "--password",
                "p",
                "--subset",
                "medium",
                "--max-videos",
                "50",
                "--skip-upload",
                "--fresh",
                "--concurrency",
                "5",
            ]
        )
        assert args.subset == "medium"
        assert args.max_videos == 50
        assert args.skip_upload is True
        assert args.fresh is True
        assert args.concurrency == 5

    def test_parse_args_missing_api_url(self):
        from evaluation.run_video_mme_eval import parse_args

        with pytest.raises(SystemExit):
            parse_args([])
