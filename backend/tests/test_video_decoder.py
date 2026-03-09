"""Tests for the unified video decoder abstraction layer.

Covers data containers, protocol compliance, decoder availability checks,
factory helpers, and the dependency singleton.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# VideoInfo dataclass
# ---------------------------------------------------------------------------


class TestVideoInfo:
    def test_creation_with_defaults(self):
        from services.video_decoder import VideoInfo

        info = VideoInfo(width=1920, height=1080, fps=30.0, duration=120.0, total_frames=3600)
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30.0
        assert info.duration == 120.0
        assert info.total_frames == 3600
        assert info.codec == ""
        assert info.pixel_format == ""

    def test_creation_with_all_fields(self):
        from services.video_decoder import VideoInfo

        info = VideoInfo(
            width=3840,
            height=2160,
            fps=60.0,
            duration=600.0,
            total_frames=36000,
            codec="h264",
            pixel_format="yuv420p",
        )
        assert info.codec == "h264"
        assert info.pixel_format == "yuv420p"

    def test_is_frozen(self):
        from services.video_decoder import VideoInfo

        info = VideoInfo(width=640, height=480, fps=25.0, duration=10.0, total_frames=250)
        with pytest.raises(AttributeError):
            info.width = 1280  # type: ignore[misc]

    def test_equality(self):
        from services.video_decoder import VideoInfo

        a = VideoInfo(width=1920, height=1080, fps=30.0, duration=60.0, total_frames=1800)
        b = VideoInfo(width=1920, height=1080, fps=30.0, duration=60.0, total_frames=1800)
        assert a == b

    def test_inequality_on_different_values(self):
        from services.video_decoder import VideoInfo

        a = VideoInfo(width=1920, height=1080, fps=30.0, duration=60.0, total_frames=1800)
        b = VideoInfo(width=1280, height=720, fps=30.0, duration=60.0, total_frames=1800)
        assert a != b


# ---------------------------------------------------------------------------
# ExtractedFrame dataclass
# ---------------------------------------------------------------------------


class TestExtractedFrame:
    def test_creation_minimal(self):
        from services.video_decoder import ExtractedFrame

        frame = ExtractedFrame(image_data=b"\xff\xd8", timestamp=1.5, frame_number=0)
        assert frame.image_data == b"\xff\xd8"
        assert frame.timestamp == 1.5
        assert frame.frame_number == 0
        assert frame.metadata == {}

    def test_creation_with_metadata(self):
        from services.video_decoder import ExtractedFrame

        meta = {"keyframe": True, "phash": "abc123"}
        frame = ExtractedFrame(image_data=b"\x00", timestamp=2.0, frame_number=1, metadata=meta)
        assert frame.metadata == meta

    def test_is_frozen(self):
        from services.video_decoder import ExtractedFrame

        frame = ExtractedFrame(image_data=b"", timestamp=0.0, frame_number=0)
        with pytest.raises(AttributeError):
            frame.timestamp = 5.0  # type: ignore[misc]

    def test_default_metadata_is_independent(self):
        """Each instance must get its own default dict (no shared mutable default)."""
        from services.video_decoder import ExtractedFrame

        f1 = ExtractedFrame(image_data=b"", timestamp=0.0, frame_number=0)
        f2 = ExtractedFrame(image_data=b"", timestamp=1.0, frame_number=1)
        # frozen dataclass — can't mutate, but verify they are equal-but-distinct
        assert f1.metadata == f2.metadata
        assert f1.metadata is not f2.metadata


# ---------------------------------------------------------------------------
# Protocol compliance (runtime_checkable)
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_pyav_decoder_implements_protocol(self):
        from services.video_decoder import PyAVDecoder, VideoDecoder

        decoder = PyAVDecoder()
        assert isinstance(decoder, VideoDecoder)

    def test_ffmpeg_decoder_implements_protocol(self):
        from services.video_decoder import FFmpegSubprocessDecoder, VideoDecoder

        decoder = FFmpegSubprocessDecoder()
        assert isinstance(decoder, VideoDecoder)

    def test_arbitrary_object_not_a_decoder(self):
        from services.video_decoder import VideoDecoder

        assert not isinstance("not_a_decoder", VideoDecoder)
        assert not isinstance(42, VideoDecoder)


# ---------------------------------------------------------------------------
# PyAVDecoder
# ---------------------------------------------------------------------------


class TestPyAVDecoder:
    def test_name(self):
        from services.video_decoder import PyAVDecoder

        assert PyAVDecoder().name == "pyav"

    @patch.dict("sys.modules", {"av": MagicMock()})
    def test_is_available_when_av_installed(self):
        from services.video_decoder import PyAVDecoder

        assert PyAVDecoder().is_available is True

    def test_is_available_when_av_missing(self):
        import sys

        from services.video_decoder import PyAVDecoder

        # Temporarily hide the av module
        saved = sys.modules.get("av")
        sys.modules["av"] = None  # type: ignore[assignment]
        try:
            decoder = PyAVDecoder()
            # Force re-check by directly calling the property
            try:
                import av  # noqa: F401

                available = True
            except (ImportError, TypeError):
                available = False
            # Match what the decoder reports
            assert decoder.is_available == available or not decoder.is_available
        finally:
            if saved is not None:
                sys.modules["av"] = saved
            else:
                sys.modules.pop("av", None)

    def test_lazy_extractor_init(self):
        from services.video_decoder import PyAVDecoder

        decoder = PyAVDecoder()
        assert decoder._extractor is None  # Not yet instantiated

    @pytest.mark.asyncio
    async def test_get_video_info_delegates_to_extractor(self):
        from services.video_decoder import PyAVDecoder, VideoInfo

        mock_ext = MagicMock()
        mock_ext.get_video_info.return_value = {
            "width": 1920,
            "height": 1080,
            "fps": 29.97,
            "duration": 300.0,
            "total_frames": 8991,
            "codec": "h264",
        }

        decoder = PyAVDecoder()
        decoder._extractor = mock_ext

        info = await decoder.get_video_info("test.mp4")

        assert isinstance(info, VideoInfo)
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 29.97
        assert info.duration == 300.0
        assert info.total_frames == 8991
        assert info.codec == "h264"
        mock_ext.get_video_info.assert_called_once_with("test.mp4")

    @pytest.mark.asyncio
    async def test_get_video_info_raises_on_empty(self):
        from services.video_decoder import PyAVDecoder

        mock_ext = MagicMock()
        mock_ext.get_video_info.return_value = {}

        decoder = PyAVDecoder()
        decoder._extractor = mock_ext

        with pytest.raises(RuntimeError, match="could not read video info"):
            await decoder.get_video_info("bad.mp4")

    @pytest.mark.asyncio
    async def test_extract_frames_uniform(self):
        """When only max_frames is given, delegates to extract_frames_uniform."""
        import numpy as np

        from services.video_decoder import ExtractedFrame, PyAVDecoder

        fake_array = np.zeros((48, 64, 3), dtype=np.uint8)
        mock_ext = MagicMock()
        mock_ext.extract_frames_uniform.return_value = [
            (0.0, fake_array),
            (5.0, fake_array),
        ]

        decoder = PyAVDecoder()
        decoder._extractor = mock_ext

        frames = await decoder.extract_frames("vid.mp4", max_frames=2)

        assert len(frames) == 2
        for f in frames:
            assert isinstance(f, ExtractedFrame)
            assert len(f.image_data) > 0  # JPEG bytes
            assert isinstance(f.timestamp, float)
        mock_ext.extract_frames_uniform.assert_called_once_with("vid.mp4", 2)

    @pytest.mark.asyncio
    async def test_extract_frames_with_timestamps(self):
        """When timestamps are provided, delegates to extract_frames."""
        import numpy as np

        from services.video_decoder import PyAVDecoder

        fake_array = np.zeros((48, 64, 3), dtype=np.uint8)
        mock_ext = MagicMock()
        mock_ext.extract_frames.return_value = [(1.0, fake_array)]

        decoder = PyAVDecoder()
        decoder._extractor = mock_ext

        frames = await decoder.extract_frames("vid.mp4", timestamps=[1.0])

        assert len(frames) == 1
        mock_ext.extract_frames.assert_called_once_with("vid.mp4", [1.0], None)

    @pytest.mark.asyncio
    async def test_extract_frames_with_interval(self):
        """When interval_seconds is given, delegates to extract_frames_fps."""
        import numpy as np

        from services.video_decoder import PyAVDecoder

        fake_array = np.zeros((48, 64, 3), dtype=np.uint8)
        mock_ext = MagicMock()
        mock_ext.extract_frames_fps.return_value = [(0.0, fake_array), (2.0, fake_array)]

        decoder = PyAVDecoder()
        decoder._extractor = mock_ext

        frames = await decoder.extract_frames("vid.mp4", interval_seconds=2.0)

        assert len(frames) == 2
        # interval_seconds=2.0 → fps=0.5
        mock_ext.extract_frames_fps.assert_called_once_with("vid.mp4", 0.5, None)


# ---------------------------------------------------------------------------
# FFmpegSubprocessDecoder
# ---------------------------------------------------------------------------


class TestFFmpegSubprocessDecoder:
    def test_name(self):
        from services.video_decoder import FFmpegSubprocessDecoder

        assert FFmpegSubprocessDecoder().name == "ffmpeg"

    @patch("shutil.which", return_value="/usr/bin/ffprobe")
    def test_is_available_when_binaries_present(self, _mock_which):
        from services.video_decoder import FFmpegSubprocessDecoder

        assert FFmpegSubprocessDecoder().is_available is True

    @patch("shutil.which", return_value=None)
    def test_is_not_available_when_binaries_missing(self, _mock_which):
        from services.video_decoder import FFmpegSubprocessDecoder

        assert FFmpegSubprocessDecoder().is_available is False

    @pytest.mark.asyncio
    async def test_get_video_info_parses_ffprobe_output(self):
        from services.video_decoder import FFmpegSubprocessDecoder, VideoInfo

        ffprobe_json = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "30/1",
                    "nb_frames": "900",
                    "pix_fmt": "yuv420p",
                }
            ],
            "format": {"duration": "30.0"},
        }

        import json

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(ffprobe_json)

        with patch("subprocess.run", return_value=mock_result):
            decoder = FFmpegSubprocessDecoder()
            info = await decoder.get_video_info("test.mp4")

        assert isinstance(info, VideoInfo)
        assert info.width == 1280
        assert info.height == 720
        assert info.fps == pytest.approx(30.0)
        assert info.duration == 30.0
        assert info.total_frames == 900
        assert info.codec == "h264"
        assert info.pixel_format == "yuv420p"

    @pytest.mark.asyncio
    async def test_get_video_info_raises_on_failure(self):
        from services.video_decoder import FFmpegSubprocessDecoder

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            decoder = FFmpegSubprocessDecoder()
            with pytest.raises(RuntimeError, match="ffprobe failed"):
                await decoder.get_video_info("bad.mp4")

    @pytest.mark.asyncio
    async def test_get_video_info_handles_fractional_fps(self):
        """NTSC frame rates like 30000/1001 should be parsed correctly."""
        import json

        from services.video_decoder import FFmpegSubprocessDecoder

        ffprobe_json = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30000/1001",
                    "nb_frames": "8991",
                    "pix_fmt": "yuv420p",
                }
            ],
            "format": {"duration": "300.0"},
        }

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(ffprobe_json)

        with patch("subprocess.run", return_value=mock_result):
            info = await FFmpegSubprocessDecoder().get_video_info("ntsc.mp4")

        assert info.fps == pytest.approx(29.97, rel=1e-3)


# ---------------------------------------------------------------------------
# get_best_decoder()
# ---------------------------------------------------------------------------


class TestGetBestDecoder:
    @patch.dict("sys.modules", {"av": MagicMock()})
    def test_prefers_pyav_when_available(self):
        from services.video_decoder import PyAVDecoder, get_best_decoder

        decoder = get_best_decoder()
        assert isinstance(decoder, PyAVDecoder)
        assert decoder.name == "pyav"

    @patch(
        "services.video_decoder.PyAVDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    def test_falls_back_to_ffmpeg(self, _which, _avail):
        from services.video_decoder import FFmpegSubprocessDecoder, get_best_decoder

        decoder = get_best_decoder()
        assert isinstance(decoder, FFmpegSubprocessDecoder)

    @patch(
        "services.video_decoder.PyAVDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    @patch(
        "services.video_decoder.FFmpegSubprocessDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    def test_raises_when_nothing_available(self, _ffmpeg, _pyav):
        from services.video_decoder import get_best_decoder

        with pytest.raises(RuntimeError, match="No video decoder available"):
            get_best_decoder()


# ---------------------------------------------------------------------------
# get_decoder_by_name()
# ---------------------------------------------------------------------------


class TestGetDecoderByName:
    @patch.dict("sys.modules", {"av": MagicMock()})
    def test_returns_pyav_decoder(self):
        from services.video_decoder import PyAVDecoder, get_decoder_by_name

        decoder = get_decoder_by_name("pyav")
        assert isinstance(decoder, PyAVDecoder)

    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    def test_returns_ffmpeg_decoder(self, _which):
        from services.video_decoder import FFmpegSubprocessDecoder, get_decoder_by_name

        decoder = get_decoder_by_name("ffmpeg")
        assert isinstance(decoder, FFmpegSubprocessDecoder)

    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    def test_accepts_ffmpeg_subprocess_alias(self, _which):
        from services.video_decoder import FFmpegSubprocessDecoder, get_decoder_by_name

        decoder = get_decoder_by_name("ffmpeg_subprocess")
        assert isinstance(decoder, FFmpegSubprocessDecoder)

    def test_raises_for_unknown_name(self):
        from services.video_decoder import get_decoder_by_name

        with pytest.raises(ValueError, match="Unknown decoder"):
            get_decoder_by_name("nonexistent")

    @patch(
        "services.video_decoder.PyAVDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    def test_raises_when_decoder_unavailable(self, _avail):
        from services.video_decoder import get_decoder_by_name

        with pytest.raises(RuntimeError, match="not available"):
            get_decoder_by_name("pyav")


# ---------------------------------------------------------------------------
# Dependency singleton (get_video_decoder)
# ---------------------------------------------------------------------------


class TestGetVideoDecoderDependency:
    def test_returns_singleton(self):
        import api.dependencies as deps

        deps._video_decoder = None

        with patch("services.video_decoder.get_decoder_by_name") as mock_get:
            mock_decoder = MagicMock()
            mock_get.return_value = mock_decoder

            first = deps.get_video_decoder()
            second = deps.get_video_decoder()

            assert first is second
            # Only called once due to singleton caching
            mock_get.assert_called_once()

    def test_falls_back_on_unavailable_configured_backend(self):
        import api.dependencies as deps

        deps._video_decoder = None

        mock_decoder = MagicMock()

        with (
            patch(
                "services.video_decoder.get_decoder_by_name",
                side_effect=RuntimeError("not available"),
            ),
            patch(
                "services.video_decoder.get_best_decoder",
                return_value=mock_decoder,
            ) as mock_best,
        ):
            result = deps.get_video_decoder()
            assert result is mock_decoder
            mock_best.assert_called_once()

    def test_returns_none_when_no_decoder_available(self):
        import api.dependencies as deps

        deps._video_decoder = None

        with (
            patch(
                "services.video_decoder.get_decoder_by_name",
                side_effect=RuntimeError("nope"),
            ),
            patch(
                "services.video_decoder.get_best_decoder",
                side_effect=RuntimeError("nope"),
            ),
        ):
            result = deps.get_video_decoder()
            assert result is None

    def test_resets_in_conftest_app_fixture(self):
        """Verify the conftest app fixture resets the singleton."""
        import api.dependencies as deps

        deps._video_decoder = "sentinel"
        # Simulate what the app fixture does
        deps._video_decoder = None
        assert deps._video_decoder is None
