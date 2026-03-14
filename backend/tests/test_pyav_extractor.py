"""Tests for PyAVFrameExtractor and the pyav integration path."""

from __future__ import annotations

from fractions import Fraction
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_frame(width: int = 64, height: int = 48, pts: int = 0, time_base=None):
    """Return a mock av.VideoFrame-like object."""
    if time_base is None:
        time_base = Fraction(1, 1000)
    frame = MagicMock()
    frame.pts = pts
    frame.width = width
    frame.height = height

    def _to_ndarray(format="rgb24"):
        return np.zeros((height, width, 3), dtype=np.uint8)

    frame.to_ndarray = _to_ndarray
    return frame


def _fake_packet(is_keyframe: bool = False, dts: int = 0, frames=None):
    """Return a mock av.Packet-like object."""
    pkt = MagicMock()
    pkt.is_keyframe = is_keyframe
    pkt.dts = dts
    pkt.decode = MagicMock(return_value=frames or [])
    return pkt


# ---------------------------------------------------------------------------
# is_pyav_available
# ---------------------------------------------------------------------------


class TestIsPyavAvailable:
    def test_returns_bool(self):
        from services.pyav_extractor import is_pyav_available

        assert isinstance(is_pyav_available(), bool)


# ---------------------------------------------------------------------------
# get_video_info
# ---------------------------------------------------------------------------


class TestGetVideoInfo:
    @patch("services.pyav_extractor._AV_AVAILABLE", False)
    def test_returns_empty_dict_when_av_missing(self):
        from services.pyav_extractor import PyAVFrameExtractor

        assert PyAVFrameExtractor.get_video_info("dummy.mp4") == {}

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_returns_metadata(self, mock_open):
        from services.pyav_extractor import PyAVFrameExtractor

        # Build a mock container
        video_stream = MagicMock()
        video_stream.average_rate = 30
        video_stream.frames = 900
        video_stream.codec_context.width = 1920
        video_stream.codec_context.height = 1080
        video_stream.codec_context.name = "h264"

        container = MagicMock()
        container.duration = 30_000_000  # 30 s in AV_TIME_BASE
        container.streams.video = [video_stream]
        container.streams.audio = [MagicMock(), MagicMock()]
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)

        mock_open.return_value = container

        info = PyAVFrameExtractor.get_video_info("video.mp4")

        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["fps"] == 30.0
        assert info["codec"] == "h264"
        assert info["total_frames"] == 900
        assert info["audio_streams"] == 2
        assert info["duration"] > 0


# ---------------------------------------------------------------------------
# extract_frames
# ---------------------------------------------------------------------------


class TestExtractFrames:
    @patch("services.pyav_extractor._AV_AVAILABLE", False)
    def test_returns_empty_when_av_missing(self):
        from services.pyav_extractor import PyAVFrameExtractor

        assert PyAVFrameExtractor.extract_frames("x.mp4", [1.0, 2.0]) == []

    def test_returns_empty_for_empty_timestamps(self):
        from services.pyav_extractor import PyAVFrameExtractor

        assert PyAVFrameExtractor.extract_frames("x.mp4", []) == []

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_extracts_requested_timestamps(self, mock_open):
        from services.pyav_extractor import PyAVFrameExtractor

        frame1 = _fake_frame(pts=1000)
        frame2 = _fake_frame(pts=2000)

        stream = MagicMock()
        stream.time_base = Fraction(1, 1000)
        stream.thread_type = None

        # decode yields one frame per call
        container = MagicMock()
        container.streams.video = [stream]
        container.decode = MagicMock(side_effect=[[frame1], [frame2]])
        container.seek = MagicMock()
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)

        mock_open.return_value = container

        results = PyAVFrameExtractor.extract_frames("vid.mp4", [1.0, 2.0])

        assert len(results) == 2
        for ts, arr in results:
            assert isinstance(ts, float)
            assert isinstance(arr, np.ndarray)
            assert arr.shape == (48, 64, 3)

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_max_frames_limits_output(self, mock_open):
        from services.pyav_extractor import PyAVFrameExtractor

        frame = _fake_frame(pts=500)

        stream = MagicMock()
        stream.time_base = Fraction(1, 1000)
        stream.thread_type = None

        container = MagicMock()
        container.streams.video = [stream]
        container.decode = MagicMock(return_value=[frame])
        container.seek = MagicMock()
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)

        mock_open.return_value = container

        results = PyAVFrameExtractor.extract_frames("vid.mp4", [0.5, 1.0, 1.5, 2.0], max_frames=2)

        # Only 2 timestamps should have been processed
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# extract_keyframes
# ---------------------------------------------------------------------------


class TestExtractKeyframes:
    @patch("services.pyav_extractor._AV_AVAILABLE", False)
    def test_returns_empty_when_av_missing(self):
        from services.pyav_extractor import PyAVFrameExtractor

        assert PyAVFrameExtractor.extract_keyframes("x.mp4") == []

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_only_keyframes_returned(self, mock_open):
        from services.pyav_extractor import PyAVFrameExtractor

        kf = _fake_frame(pts=0)
        non_kf_frame = _fake_frame(pts=500)

        pkt_key = _fake_packet(is_keyframe=True, dts=0, frames=[kf])
        pkt_normal = _fake_packet(is_keyframe=False, dts=500, frames=[non_kf_frame])

        stream = MagicMock()
        stream.time_base = Fraction(1, 1000)
        stream.thread_type = None

        container = MagicMock()
        container.streams.video = [stream]
        container.demux = MagicMock(return_value=[pkt_key, pkt_normal])
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)

        mock_open.return_value = container

        results = PyAVFrameExtractor.extract_keyframes("vid.mp4")
        assert len(results) == 1
        assert results[0][0] == 0.0

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_max_frames_respected(self, mock_open):
        from services.pyav_extractor import PyAVFrameExtractor

        kf1 = _fake_frame(pts=0)
        kf2 = _fake_frame(pts=1000)

        pkt1 = _fake_packet(is_keyframe=True, dts=0, frames=[kf1])
        pkt2 = _fake_packet(is_keyframe=True, dts=1000, frames=[kf2])

        stream = MagicMock()
        stream.time_base = Fraction(1, 1000)
        stream.thread_type = None

        container = MagicMock()
        container.streams.video = [stream]
        container.demux = MagicMock(return_value=[pkt1, pkt2])
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)

        mock_open.return_value = container

        results = PyAVFrameExtractor.extract_keyframes("vid.mp4", max_frames=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# detect_scenes_basic
# ---------------------------------------------------------------------------


class TestDetectScenesBasic:
    @patch("services.pyav_extractor._AV_AVAILABLE", False)
    def test_returns_empty_when_av_missing(self):
        from services.pyav_extractor import PyAVFrameExtractor

        assert PyAVFrameExtractor.detect_scenes_basic("x.mp4") == []


# ---------------------------------------------------------------------------
# extract_frames_uniform / extract_frames_fps (high-level wrappers)
# ---------------------------------------------------------------------------


class TestHighLevelWrappers:
    @patch("services.pyav_extractor.PyAVFrameExtractor.get_video_info")
    @patch("services.pyav_extractor.PyAVFrameExtractor.extract_frames")
    def test_extract_frames_uniform_computes_timestamps(self, mock_extract, mock_info):
        from services.pyav_extractor import PyAVFrameExtractor

        mock_info.return_value = {"duration": 10.0}
        mock_extract.return_value = []

        PyAVFrameExtractor.extract_frames_uniform("vid.mp4", num_frames=5)

        mock_extract.assert_called_once()
        timestamps = mock_extract.call_args[0][1]  # second positional arg
        assert len(timestamps) == 5
        assert timestamps[0] == pytest.approx(0.0)

    @patch("services.pyav_extractor.PyAVFrameExtractor.get_video_info")
    @patch("services.pyav_extractor.PyAVFrameExtractor.extract_frames")
    def test_extract_frames_uniform_returns_empty_for_zero_duration(self, mock_extract, mock_info):
        from services.pyav_extractor import PyAVFrameExtractor

        mock_info.return_value = {"duration": 0.0}

        result = PyAVFrameExtractor.extract_frames_uniform("vid.mp4", num_frames=5)
        assert result == []
        mock_extract.assert_not_called()

    @patch("services.pyav_extractor.PyAVFrameExtractor.get_video_info")
    @patch("services.pyav_extractor.PyAVFrameExtractor.extract_frames")
    def test_extract_frames_fps_computes_timestamps(self, mock_extract, mock_info):
        from services.pyav_extractor import PyAVFrameExtractor

        mock_info.return_value = {"duration": 5.0}
        mock_extract.return_value = []

        PyAVFrameExtractor.extract_frames_fps("vid.mp4", fps=1.0)

        mock_extract.assert_called_once()
        timestamps = mock_extract.call_args[0][1]
        # At 1fps over 5s → [0, 1, 2, 3, 4]
        assert len(timestamps) == 5
        assert timestamps[0] == pytest.approx(0.0)
        assert timestamps[-1] == pytest.approx(4.0)

    def test_extract_frames_fps_returns_empty_for_zero_fps(self):
        from services.pyav_extractor import PyAVFrameExtractor

        result = PyAVFrameExtractor.extract_frames_fps("vid.mp4", fps=0.0)
        assert result == []


# ---------------------------------------------------------------------------
# FFmpegVideoProcessor backend resolution
# ---------------------------------------------------------------------------


class TestDecoderBackendResolution:
    """Ensure the FFmpegVideoProcessor picks the right backend."""

    @patch("services.pyav_extractor.is_pyav_available", return_value=True)
    def test_default_backend_is_pyav(self, _):
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor()
        assert proc._decoder_backend == "pyav"

    @patch("services.pyav_extractor.is_pyav_available", return_value=False)
    def test_fallback_to_subprocess_when_av_unavailable(self, _):
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor()
        assert proc._decoder_backend == "ffmpeg_subprocess"

    def test_explicit_subprocess_backend(self):
        from models.ffmpeg_config import FFmpegProcessingConfig, FrameExtractionConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        config = FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(decoder_backend="ffmpeg_subprocess")
        )
        proc = FFmpegVideoProcessor(config=config)
        assert proc._decoder_backend == "ffmpeg_subprocess"


# ---------------------------------------------------------------------------
# Config model additions
# ---------------------------------------------------------------------------


class TestConfigAdditions:
    def test_frame_extraction_config_has_decoder_backend(self):
        from models.ffmpeg_config import FrameExtractionConfig

        cfg = FrameExtractionConfig()
        assert cfg.decoder_backend == "pyav"

    def test_frame_extraction_config_accepts_subprocess(self):
        from models.ffmpeg_config import FrameExtractionConfig

        cfg = FrameExtractionConfig(decoder_backend="ffmpeg_subprocess")
        assert cfg.decoder_backend == "ffmpeg_subprocess"

    def test_app_settings_has_video_decoder_backend(self, reset_settings):
        from core.config import AppSettings

        s = AppSettings()
        assert s.video_decoder_backend == "pyav"


# ---------------------------------------------------------------------------
# Dependency getter
# ---------------------------------------------------------------------------


class TestDependencyGetter:
    def test_get_pyav_extractor_returns_instance_or_none(self):
        import api.dependencies as deps

        deps._pyav_extractor = None
        result = deps.get_pyav_extractor()
        # Either a PyAVFrameExtractor or None (if av not installed)
        if result is not None:
            from services.pyav_extractor import PyAVFrameExtractor

            assert isinstance(result, PyAVFrameExtractor)

    def test_get_pyav_extractor_returns_same_singleton(self):
        import api.dependencies as deps

        deps._pyav_extractor = None
        first = deps.get_pyav_extractor()
        second = deps.get_pyav_extractor()
        assert first is second
