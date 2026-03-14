"""Tests for services/scene_detect_service.py and FFmpeg integration."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from services.scene_detect_service import (
    SceneDetectService,
    SceneInfo,
    map_ffmpeg_threshold,
)

pytestmark = pytest.mark.unit


# =============================================================================
# map_ffmpeg_threshold
# =============================================================================


class TestMapFfmpegThreshold:
    """Verify FFmpeg → PySceneDetect threshold mapping."""

    def test_adaptive_low(self) -> None:
        # FFmpeg 0.0 → most sensitive adaptive
        result = map_ffmpeg_threshold(0.0, method="adaptive")
        assert result == pytest.approx(1.5)

    def test_adaptive_high(self) -> None:
        # FFmpeg 1.0 → least sensitive adaptive
        result = map_ffmpeg_threshold(1.0, method="adaptive")
        assert result == pytest.approx(5.0)

    def test_adaptive_mid(self) -> None:
        result = map_ffmpeg_threshold(0.5, method="adaptive")
        assert 3.0 < result < 3.5  # roughly in the middle

    def test_content_low(self) -> None:
        result = map_ffmpeg_threshold(0.0, method="content")
        assert result == pytest.approx(15.0)

    def test_content_high(self) -> None:
        result = map_ffmpeg_threshold(1.0, method="content")
        assert result == pytest.approx(40.0)

    def test_clamps_below_zero(self) -> None:
        result = map_ffmpeg_threshold(-0.5, method="adaptive")
        assert result == map_ffmpeg_threshold(0.0, method="adaptive")

    def test_clamps_above_one(self) -> None:
        result = map_ffmpeg_threshold(2.0, method="content")
        assert result == map_ffmpeg_threshold(1.0, method="content")


# =============================================================================
# SceneDetectService — library unavailable
# =============================================================================


class TestSceneDetectServiceNoLibrary:
    """When PySceneDetect is not installed every method should return an empty list."""

    def test_detect_scenes_returns_empty(self) -> None:
        service = SceneDetectService()
        with patch("services.scene_detect_service._check_scenedetect", return_value=False):
            result = service.detect_scenes("/fake/video.mp4")
        assert result == []

    def test_detect_scene_timestamps_returns_empty(self) -> None:
        service = SceneDetectService()
        with patch("services.scene_detect_service._check_scenedetect", return_value=False):
            result = service.detect_scene_timestamps("/fake/video.mp4")
        assert result == []

    def test_get_scene_frames_returns_empty(self) -> None:
        service = SceneDetectService()
        with patch("services.scene_detect_service._check_scenedetect", return_value=False):
            result = service.get_scene_frames("/fake/video.mp4")
        assert result == []


# =============================================================================
# SceneDetectService — invalid inputs
# =============================================================================


class TestSceneDetectServiceInvalidInputs:
    """Edge-case handling for missing / empty paths."""

    def test_empty_path(self) -> None:
        service = SceneDetectService()
        with patch("services.scene_detect_service._check_scenedetect", return_value=True):
            assert service.detect_scenes("") == []

    def test_nonexistent_path(self) -> None:
        service = SceneDetectService()
        with patch("services.scene_detect_service._check_scenedetect", return_value=True):
            assert service.detect_scenes("/no/such/file.mp4") == []


# =============================================================================
# SceneDetectService — mocked PySceneDetect
# =============================================================================


def _make_mock_timecode(seconds: float, frames: int) -> MagicMock:
    """Create a mock FrameTimecode with .get_seconds() and .get_frames()."""
    tc = MagicMock()
    tc.get_seconds.return_value = seconds
    tc.get_frames.return_value = frames
    return tc


class TestSceneDetectServiceWithMocks:
    """Test detection logic with PySceneDetect internals mocked out."""

    @pytest.fixture(autouse=True)
    def _mock_scenedetect_modules(self):
        """Inject mock scenedetect modules so patches resolve without install."""
        mock_sd = MagicMock()
        mock_detectors = MagicMock()
        mock_sd.detectors = mock_detectors
        with patch.dict(
            sys.modules,
            {
                "scenedetect": mock_sd,
                "scenedetect.detectors": mock_detectors,
            },
        ):
            yield

    def test_detect_scenes_adaptive(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_scene_list = [
            (_make_mock_timecode(0.0, 0), _make_mock_timecode(5.0, 150)),
            (_make_mock_timecode(5.0, 150), _make_mock_timecode(12.0, 360)),
        ]

        mock_manager = MagicMock()
        mock_manager.get_scene_list.return_value = mock_scene_list

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.AdaptiveDetector") as mock_adaptive,
        ):
            service = SceneDetectService()
            scenes = service.detect_scenes(str(video_file), method="adaptive")

        assert len(scenes) == 2
        assert scenes[0] == SceneInfo(start_time=0.0, end_time=5.0, start_frame=0, end_frame=150)
        assert scenes[1].start_time == pytest.approx(5.0)
        mock_adaptive.assert_called_once()
        mock_manager.detect_scenes.assert_called_once()

    def test_detect_scenes_content(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_scene_list = [
            (_make_mock_timecode(0.0, 0), _make_mock_timecode(10.0, 300)),
        ]

        mock_manager = MagicMock()
        mock_manager.get_scene_list.return_value = mock_scene_list

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.ContentDetector") as mock_content,
        ):
            service = SceneDetectService()
            scenes = service.detect_scenes(str(video_file), method="content", threshold=30.0)

        assert len(scenes) == 1
        mock_content.assert_called_once_with(threshold=30.0)

    def test_detect_scenes_no_results(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_manager = MagicMock()
        mock_manager.get_scene_list.return_value = []

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.AdaptiveDetector"),
        ):
            service = SceneDetectService()
            assert service.detect_scenes(str(video_file)) == []

    def test_detect_scene_timestamps(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_scene_list = [
            (_make_mock_timecode(0.0, 0), _make_mock_timecode(4.0, 120)),
            (_make_mock_timecode(4.0, 120), _make_mock_timecode(9.5, 285)),
        ]

        mock_manager = MagicMock()
        mock_manager.get_scene_list.return_value = mock_scene_list

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.AdaptiveDetector"),
        ):
            service = SceneDetectService()
            ts = service.detect_scene_timestamps(str(video_file))

        assert ts == [0.0, 4.0]

    def test_get_scene_frames(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_scene_list = [
            (_make_mock_timecode(0.0, 0), _make_mock_timecode(10.0, 300)),
        ]

        mock_manager = MagicMock()
        mock_manager.get_scene_list.return_value = mock_scene_list

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.AdaptiveDetector"),
        ):
            service = SceneDetectService()
            frames = service.get_scene_frames(str(video_file))

        assert len(frames) == 1
        mid_time, mid_frame = frames[0]
        assert mid_time == pytest.approx(5.0)
        assert mid_frame == 150

    def test_open_video_exception(self, tmp_path) -> None:
        video_file = tmp_path / "corrupt.mp4"
        video_file.write_bytes(b"\x00" * 64)

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video", side_effect=RuntimeError("corrupt")),
        ):
            service = SceneDetectService()
            assert service.detect_scenes(str(video_file)) == []

    def test_detect_scenes_analysis_exception(self, tmp_path) -> None:
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        mock_manager = MagicMock()
        mock_manager.detect_scenes.side_effect = RuntimeError("analysis failed")

        with (
            patch("services.scene_detect_service._check_scenedetect", return_value=True),
            patch("services.scene_detect_service.os.path.exists", return_value=True),
            patch("scenedetect.open_video"),
            patch("scenedetect.SceneManager", return_value=mock_manager),
            patch("scenedetect.detectors.AdaptiveDetector"),
        ):
            service = SceneDetectService()
            assert service.detect_scenes(str(video_file)) == []


# =============================================================================
# FFmpegVideoProcessor integration
# =============================================================================


class TestFFmpegProcessorPySceneDetectIntegration:
    """Verify the FFmpegVideoProcessor delegates to PySceneDetect."""

    def test_uses_pyscenedetect_by_default(self) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor()
        assert proc._use_pyscenedetect is True

    def test_detect_delegates_to_service(self, tmp_path) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        proc = FFmpegVideoProcessor()
        proc._scene_detect_service = MagicMock()
        proc._scene_detect_service.detect_scene_timestamps.return_value = [0.0, 3.5, 8.2]

        result = proc._detect_scene_timestamps(str(video_file), 0.4, 10)

        proc._scene_detect_service.detect_scene_timestamps.assert_called_once()
        assert result == [0.0, 3.5, 8.2]

    def test_falls_back_to_ffmpeg_when_disabled(self, tmp_path) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        proc = FFmpegVideoProcessor()
        proc._use_pyscenedetect = False

        with patch.object(proc, "_detect_scene_timestamps_ffmpeg", return_value=[1.0]) as mock_ff:
            result = proc._detect_scene_timestamps(str(video_file), 0.3, 5)

        mock_ff.assert_called_once_with(str(video_file), 0.3, 5)
        assert result == [1.0]

    def test_falls_back_when_pyscenedetect_empty(self, tmp_path) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        proc = FFmpegVideoProcessor()
        proc._scene_detect_service = MagicMock()
        proc._scene_detect_service.detect_scene_timestamps.return_value = []

        with patch.object(proc, "_detect_scene_timestamps_ffmpeg", return_value=[2.5]) as mock_ff:
            result = proc._detect_scene_timestamps(str(video_file), 0.3, 5)

        # Should have tried PySceneDetect first, then fallen back
        proc._scene_detect_service.detect_scene_timestamps.assert_called_once()
        mock_ff.assert_called_once()
        assert result == [2.5]

    def test_max_scenes_respected(self, tmp_path) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 64)

        proc = FFmpegVideoProcessor()
        proc._scene_detect_service = MagicMock()
        proc._scene_detect_service.detect_scene_timestamps.return_value = [
            0.0,
            2.0,
            4.0,
            6.0,
            8.0,
            10.0,
        ]

        result = proc._detect_scene_timestamps(str(video_file), 0.3, 3)
        assert len(result) == 3

    def test_nonexistent_path_returns_empty(self) -> None:
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor()
        result = proc._detect_scene_timestamps("/does/not/exist.mp4", 0.3, 10)
        assert result == []


# =============================================================================
# dependencies.get_scene_detect_service
# =============================================================================


class TestGetSceneDetectServiceDependency:
    """Verify the singleton getter in api/dependencies.py."""

    def test_returns_singleton(self) -> None:
        import api.dependencies as deps

        # Reset global state
        deps._scene_detect_service = None
        svc1 = deps.get_scene_detect_service()
        svc2 = deps.get_scene_detect_service()
        assert svc1 is svc2
        assert isinstance(svc1, SceneDetectService)
        # Clean up
        deps._scene_detect_service = None
