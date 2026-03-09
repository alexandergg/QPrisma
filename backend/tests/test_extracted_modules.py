"""
Tests for extracted video processing modules.

Covers:
- HardwareAccelerationResolver (hwaccel_resolver.py)
- TimestampCalculator (timestamp_calculator.py)
- CoverageAnalyzer (coverage_analyzer.py)

These tests verify that the extracted modules produce identical results
to the original FFmpegVideoProcessor methods.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ===========================================================================
# HardwareAccelerationResolver
# ===========================================================================


@pytest.mark.unit
class TestHardwareAccelerationResolver:
    def test_resolve_auto_delegates_to_detect(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        with patch.object(HardwareAccelerationResolver, "detect_available", return_value="cuda"):
            assert HardwareAccelerationResolver.resolve("auto") == "cuda"

    def test_resolve_explicit_value(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        assert HardwareAccelerationResolver.resolve("qsv") == "qsv"

    def test_resolve_none(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        assert HardwareAccelerationResolver.resolve(None) is None

    def test_resolve_empty_string(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        assert HardwareAccelerationResolver.resolve("") is None

    def test_build_args_with_hwaccel(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        assert HardwareAccelerationResolver.build_args("cuda") == ["-hwaccel", "cuda"]

    def test_build_args_without_hwaccel(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        assert HardwareAccelerationResolver.build_args(None) == []

    def test_detect_available_caches_result(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        # Reset cache
        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

        mock_result = MagicMock()
        mock_result.stdout = "cuda\nvaapi\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result1 = HardwareAccelerationResolver.detect_available()
            result2 = HardwareAccelerationResolver.detect_available()

        assert result1 == "cuda"
        assert result2 == "cuda"
        # subprocess.run should be called only once (cached)
        mock_run.assert_called_once()

        # Reset cache for other tests
        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

    def test_detect_available_no_gpu(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

        mock_result = MagicMock()
        mock_result.stdout = "Hardware acceleration methods:\n"

        with patch("subprocess.run", return_value=mock_result):
            result = HardwareAccelerationResolver.detect_available()

        assert result is None

        # Reset cache
        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

    def test_detect_available_subprocess_failure(self):
        from services.hwaccel_resolver import HardwareAccelerationResolver

        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

        with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            result = HardwareAccelerationResolver.detect_available()

        assert result is None

        # Reset cache
        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None


# ===========================================================================
# TimestampCalculator
# ===========================================================================


@pytest.mark.unit
class TestTimestampCalculator:
    def _make_extraction(self, **kwargs):
        from models.ffmpeg_config import FrameExtractionConfig

        return FrameExtractionConfig(**kwargs)

    def test_uniform_timestamps(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="uniform", num_frames=5, max_frames=100)
        video_info = {"duration": 100.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert len(ts) == 5
        assert ts[0] == pytest.approx(0.0)
        assert ts[-1] == pytest.approx(99.9)  # min(100.0, 100.0 - 0.1)

    def test_interval_timestamps(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="interval", interval_seconds=10.0, max_frames=100)
        video_info = {"duration": 55.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert len(ts) == 6  # 0, 10, 20, 30, 40, 50
        assert ts[0] == pytest.approx(0.0)
        assert ts[-1] == pytest.approx(50.0)

    def test_fps_timestamps(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="fps", fps=2.0, max_frames=10)
        video_info = {"duration": 3.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert len(ts) == 6  # 0.0, 0.5, 1.0, 1.5, 2.0, 2.5
        assert ts[0] == pytest.approx(0.0)
        assert ts[-1] == pytest.approx(2.5)

    def test_keyframes_returns_empty(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="keyframes")
        video_info = {"duration": 100.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert ts == []

    def test_scene_detect_returns_empty(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="scene_detect")
        video_info = {"duration": 100.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert ts == []

    def test_zero_duration_returns_empty(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="uniform", num_frames=5, max_frames=100)
        video_info = {"duration": 0.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert ts == []

    def test_max_frames_limit(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="interval", interval_seconds=1.0, max_frames=5)
        video_info = {"duration": 100.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert len(ts) == 5

    def test_hybrid_with_scene_detector(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="hybrid", max_frames=20)
        video_info = {"duration": 60.0, "path": "/fake/video.mp4"}

        scene_detector = MagicMock(return_value=[10.0, 30.0, 50.0])

        ts = calc.calculate_frame_timestamps(video_info, extraction, scene_detector)
        assert len(ts) > 0
        assert len(ts) <= 20
        scene_detector.assert_called_once()

    def test_hybrid_fallback_to_uniform_when_no_scenes(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="hybrid", max_frames=10)
        video_info = {"duration": 60.0, "path": "/fake/video.mp4"}

        scene_detector = MagicMock(return_value=[])

        ts = calc.calculate_frame_timestamps(video_info, extraction, scene_detector)
        assert len(ts) == 10  # Falls back to uniform

    def test_hybrid_without_scene_detector(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(method="hybrid", max_frames=10)
        video_info = {"duration": 60.0, "path": "/fake/video.mp4"}

        ts = calc.calculate_frame_timestamps(video_info, extraction, scene_detector=None)
        # Without detector, falls back to uniform
        assert len(ts) == 10

    def test_start_end_time(self):
        from services.timestamp_calculator import TimestampCalculator

        calc = TimestampCalculator()
        extraction = self._make_extraction(
            method="uniform", num_frames=3, max_frames=100, start_time=10.0, end_time=40.0
        )
        video_info = {"duration": 60.0}

        ts = calc.calculate_frame_timestamps(video_info, extraction)
        assert len(ts) == 3
        assert ts[0] == pytest.approx(10.0)
        assert ts[-1] == pytest.approx(40.0)


# ===========================================================================
# CoverageAnalyzer
# ===========================================================================


@pytest.mark.unit
class TestCoverageAnalyzer:
    def test_empty_timestamps(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()
        result = analyzer.calculate_coverage_metrics([], 100.0)
        assert result["coverage_score"] == 0
        assert result["recommendations"] == ["No frames extracted"]

    def test_zero_duration(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()
        result = analyzer.calculate_coverage_metrics([1.0, 2.0], 0.0)
        assert result["coverage_score"] == 0

    def test_good_coverage(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()
        # 20 frames over 60s = 20 frames/min, well above ideal (10/min)
        timestamps = [i * 3.0 for i in range(20)]
        result = analyzer.calculate_coverage_metrics(timestamps, 60.0)
        assert result["coverage_score"] > 50
        assert result["total_frames"] == 20
        assert result["density_per_minute"] == pytest.approx(20.0)

    def test_poor_coverage_large_gaps(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()
        # Only 2 frames with a 100s gap in a 120s video
        timestamps = [5.0, 115.0]
        result = analyzer.calculate_coverage_metrics(timestamps, 120.0)
        assert result["max_gap"] > 50
        assert result["total_problematic_gaps"] > 0

    def test_gap_threshold_varies_by_duration(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()

        # Short video (<5 min) → threshold 10s
        result_short = analyzer.calculate_coverage_metrics([0.0, 50.0], 60.0)
        assert result_short["gap_threshold"] == 10.0

        # Medium video (5-30 min) → threshold 20s
        result_med = analyzer.calculate_coverage_metrics([0.0, 500.0], 600.0)
        assert result_med["gap_threshold"] == 20.0

        # Long video (30-60 min) → threshold 30s
        result_long = analyzer.calculate_coverage_metrics([0.0, 2000.0], 2400.0)
        assert result_long["gap_threshold"] == 30.0

        # Very long video (>1 hour) → threshold 45s
        result_xl = analyzer.calculate_coverage_metrics([0.0, 5000.0], 7200.0)
        assert result_xl["gap_threshold"] == 45.0

    def test_output_structure(self):
        from services.coverage_analyzer import CoverageAnalyzer

        analyzer = CoverageAnalyzer()
        result = analyzer.calculate_coverage_metrics([0.0, 30.0, 60.0], 60.0)

        expected_keys = {
            "coverage_score",
            "average_gap",
            "max_gap",
            "gap_threshold",
            "gaps_over_threshold",
            "total_problematic_gaps",
            "density_per_minute",
            "total_frames",
            "video_duration",
            "recommendations",
        }
        assert set(result.keys()) == expected_keys


# ===========================================================================
# Integration: FFmpegVideoProcessor still delegates correctly
# ===========================================================================


@pytest.mark.unit
class TestFFmpegProcessorDelegation:
    """Verify that FFmpegVideoProcessor thin wrappers delegate correctly."""

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_coverage_metrics_delegation(self, _):
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor()
        result = proc.calculate_coverage_metrics([0.0, 30.0, 60.0], 60.0)
        assert "coverage_score" in result
        assert "recommendations" in result

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_hwaccel_delegator_build_args(self, _):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        config = FFmpegProcessingConfig(hardware_accel="cuda")
        proc = FFmpegVideoProcessor(config=config)
        assert proc._build_hwaccel_args() == ["-hwaccel", "cuda"]

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_hwaccel_delegator_build_args_none(self, _):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        config = FFmpegProcessingConfig(hardware_accel="")
        proc = FFmpegVideoProcessor(config=config)
        assert proc._build_hwaccel_args() == []

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_calculate_frame_timestamps_delegation(self, _):
        from models.ffmpeg_config import FFmpegProcessingConfig, FrameExtractionConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        config = FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(method="uniform", num_frames=5, max_frames=100)
        )
        proc = FFmpegVideoProcessor(config=config)
        ts = proc._calculate_frame_timestamps({"duration": 100.0})
        assert len(ts) == 5

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_detect_available_hwaccel_is_static(self, _):
        from services.ffmpeg_processor import FFmpegVideoProcessor

        # Should still be accessible as a static method
        from services.hwaccel_resolver import HardwareAccelerationResolver

        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = FFmpegVideoProcessor._detect_available_hwaccel()
        assert result is None

        HardwareAccelerationResolver._hwaccel_checked = False
        HardwareAccelerationResolver._hwaccel_available = None
