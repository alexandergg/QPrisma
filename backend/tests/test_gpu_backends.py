"""Tests for GPU backend stubs (NvVideoCodecDecoder & TransNetV2SceneDetector).

These tests validate that GPU stubs:
- Instantiate without any optional dependencies
- Report correct property values (name, is_available)
- Raise appropriate errors with helpful messages
- Integrate correctly with the decoder factory

No GPU hardware or optional packages are required to run these tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# NvVideoCodecDecoder — properties & availability
# =============================================================================


class TestNvVideoCodecDecoderProperties:
    """Verify NvVideoCodecDecoder reports correct metadata."""

    def test_name(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        assert NvVideoCodecDecoder().name == "nvvideocodec"

    def test_is_available_false_when_not_installed(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        # PyNvVideoCodec is not installed in the test environment
        decoder = NvVideoCodecDecoder()
        assert decoder.is_available is False

    @patch("services.gpu_decoder._nvcodec_available", True)
    def test_is_available_true_when_installed(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        assert decoder.is_available is True

    def test_lazy_decoder_init(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        assert decoder._decoder is None


class TestNvVideoCodecDecoderProtocol:
    """Verify NvVideoCodecDecoder conforms to the VideoDecoder protocol."""

    def test_implements_video_decoder_protocol(self):
        from services.gpu_decoder import NvVideoCodecDecoder
        from services.video_decoder import VideoDecoder

        decoder = NvVideoCodecDecoder()
        assert isinstance(decoder, VideoDecoder)


# =============================================================================
# NvVideoCodecDecoder — error behaviour
# =============================================================================


class TestNvVideoCodecDecoderErrors:
    """Verify helpful error messages when GPU is unavailable."""

    @pytest.mark.asyncio
    async def test_get_video_info_raises_when_unavailable(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        # Ensure unavailable
        with (
            patch.object(
                type(decoder), "is_available", new_callable=lambda: property(lambda self: False)
            ),
            pytest.raises(RuntimeError, match="PyNvVideoCodec is not installed"),
        ):
            await decoder.get_video_info("test.mp4")

    @pytest.mark.asyncio
    async def test_extract_frames_raises_when_unavailable(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        with (
            patch.object(
                type(decoder), "is_available", new_callable=lambda: property(lambda self: False)
            ),
            pytest.raises(RuntimeError, match="PyNvVideoCodec is not installed"),
        ):
            await decoder.extract_frames("test.mp4", max_frames=5)

    @pytest.mark.asyncio
    @patch("services.gpu_decoder._nvcodec_available", True)
    async def test_extract_frames_raises_not_implemented(self):
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        with pytest.raises(NotImplementedError, match="stub"):
            await decoder.extract_frames("test.mp4", max_frames=5)

    @pytest.mark.asyncio
    @patch("services.gpu_decoder._nvcodec_available", True)
    async def test_extract_frames_error_mentions_pyav(self):
        """Error message should guide users to the CPU alternative."""
        from services.gpu_decoder import NvVideoCodecDecoder

        decoder = NvVideoCodecDecoder()
        with pytest.raises(NotImplementedError, match="PyAVDecoder"):
            await decoder.extract_frames("test.mp4")


# =============================================================================
# NvVideoCodecDecoder — get_video_info delegation
# =============================================================================


class TestNvVideoCodecDecoderDelegation:
    """Verify get_video_info delegates to FFmpegSubprocessDecoder."""

    @pytest.mark.asyncio
    @patch("services.gpu_decoder._nvcodec_available", True)
    async def test_get_video_info_delegates_to_ffprobe(self):
        from services.gpu_decoder import NvVideoCodecDecoder
        from services.video_decoder import VideoInfo

        mock_info = VideoInfo(
            width=3840,
            height=2160,
            fps=60.0,
            duration=120.0,
            total_frames=7200,
            codec="hevc",
            pixel_format="yuv420p",
        )

        with patch(
            "services.video_decoder.FFmpegSubprocessDecoder.get_video_info",
            return_value=mock_info,
        ) as mock_get:
            decoder = NvVideoCodecDecoder()
            info = await decoder.get_video_info("4k_video.mp4")

        assert info.width == 3840
        assert info.codec == "hevc"
        mock_get.assert_called_once_with("4k_video.mp4")


# =============================================================================
# is_gpu_decoder_available()
# =============================================================================


class TestIsGpuDecoderAvailable:
    def test_returns_false_by_default(self):
        from services.gpu_decoder import is_gpu_decoder_available

        assert is_gpu_decoder_available() is False

    @patch("services.gpu_decoder._nvcodec_available", True)
    def test_returns_true_when_installed(self):
        from services.gpu_decoder import is_gpu_decoder_available

        assert is_gpu_decoder_available() is True


# =============================================================================
# TransNetV2SceneDetector — properties & availability
# =============================================================================


class TestTransNetV2SceneDetectorProperties:
    """Verify TransNetV2SceneDetector reports correct metadata."""

    def test_is_available_false_when_not_installed(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        assert detector.is_available is False

    @patch("services.gpu_scene_detector._transnetv2_available", True)
    def test_is_available_true_when_installed(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        assert detector.is_available is True

    def test_default_threshold(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        assert detector._threshold == 0.5

    def test_custom_threshold(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector(threshold=0.8)
        assert detector._threshold == 0.8

    def test_model_initially_none(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        assert detector._model is None


# =============================================================================
# TransNetV2SceneDetector — error behaviour
# =============================================================================


class TestTransNetV2SceneDetectorErrors:
    """Verify helpful error messages when TransNetV2 is unavailable."""

    @pytest.mark.asyncio
    async def test_detect_scenes_raises_when_unavailable(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        with pytest.raises(RuntimeError, match="TransNetV2 is not installed"):
            await detector.detect_scenes("test.mp4")

    @pytest.mark.asyncio
    async def test_detect_scene_timestamps_raises_when_unavailable(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        with pytest.raises(RuntimeError, match="TransNetV2 is not installed"):
            await detector.detect_scene_timestamps("test.mp4")

    @pytest.mark.asyncio
    @patch("services.gpu_scene_detector._transnetv2_available", True)
    async def test_detect_scenes_raises_not_implemented(self):
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        with pytest.raises(NotImplementedError, match="stub"):
            await detector.detect_scenes("test.mp4")

    @pytest.mark.asyncio
    @patch("services.gpu_scene_detector._transnetv2_available", True)
    async def test_detect_scenes_error_mentions_pyscenedetect(self):
        """Error message should guide users to the CPU alternative."""
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        with pytest.raises(NotImplementedError, match="SceneDetectService"):
            await detector.detect_scenes("test.mp4")

    @pytest.mark.asyncio
    @patch("services.gpu_scene_detector._transnetv2_available", True)
    async def test_detect_scene_timestamps_raises_not_implemented(self):
        """detect_scene_timestamps delegates to detect_scenes, so also NotImplementedError."""
        from services.gpu_scene_detector import TransNetV2SceneDetector

        detector = TransNetV2SceneDetector()
        with pytest.raises(NotImplementedError, match="stub"):
            await detector.detect_scene_timestamps("test.mp4")


# =============================================================================
# NeuralSceneInfo dataclass
# =============================================================================


class TestNeuralSceneInfo:
    def test_creation_with_defaults(self):
        from services.gpu_scene_detector import NeuralSceneInfo

        scene = NeuralSceneInfo(
            start_frame=0,
            end_frame=150,
            start_time=0.0,
            end_time=5.0,
            confidence=0.95,
        )
        assert scene.transition_type == "cut"
        assert scene.confidence == 0.95

    def test_creation_with_all_fields(self):
        from services.gpu_scene_detector import NeuralSceneInfo

        scene = NeuralSceneInfo(
            start_frame=100,
            end_frame=200,
            start_time=3.33,
            end_time=6.67,
            confidence=0.78,
            transition_type="dissolve",
        )
        assert scene.transition_type == "dissolve"
        assert scene.start_frame == 100

    def test_is_frozen(self):
        from services.gpu_scene_detector import NeuralSceneInfo

        scene = NeuralSceneInfo(
            start_frame=0,
            end_frame=100,
            start_time=0.0,
            end_time=3.33,
            confidence=0.9,
        )
        with pytest.raises(AttributeError):
            scene.confidence = 0.5  # type: ignore[misc]


# =============================================================================
# is_transnetv2_available()
# =============================================================================


class TestIsTransnetV2Available:
    def test_returns_false_by_default(self):
        from services.gpu_scene_detector import is_transnetv2_available

        assert is_transnetv2_available() is False

    @patch("services.gpu_scene_detector._transnetv2_available", True)
    def test_returns_true_when_installed(self):
        from services.gpu_scene_detector import is_transnetv2_available

        assert is_transnetv2_available() is True


# =============================================================================
# Factory integration — get_decoder_by_name("nvvideocodec")
# =============================================================================


class TestFactoryNvVideoCodec:
    """Verify the decoder factory recognises the GPU backend."""

    def test_get_decoder_by_name_nvvideocodec_when_unavailable(self):
        """Should raise RuntimeError when GPU deps not installed."""
        from services.video_decoder import get_decoder_by_name

        with pytest.raises(RuntimeError, match="not available"):
            get_decoder_by_name("nvvideocodec")

    @patch("services.gpu_decoder._nvcodec_available", True)
    def test_get_decoder_by_name_nvvideocodec_when_available(self):
        from services.gpu_decoder import NvVideoCodecDecoder
        from services.video_decoder import get_decoder_by_name

        decoder = get_decoder_by_name("nvvideocodec")
        assert isinstance(decoder, NvVideoCodecDecoder)
        assert decoder.name == "nvvideocodec"

    def test_unknown_decoder_name_lists_nvvideocodec(self):
        """The error message for unknown names should include nvvideocodec."""
        from services.video_decoder import get_decoder_by_name

        with pytest.raises(ValueError, match="nvvideocodec"):
            get_decoder_by_name("nonexistent")


# =============================================================================
# Factory integration — get_best_decoder GPU priority
# =============================================================================


class TestGetBestDecoderGPUPriority:
    """Verify GPU decoder is preferred over CPU decoders."""

    @patch("services.gpu_decoder._nvcodec_available", True)
    def test_prefers_gpu_when_available(self):
        from services.gpu_decoder import NvVideoCodecDecoder
        from services.video_decoder import get_best_decoder

        decoder = get_best_decoder()
        assert isinstance(decoder, NvVideoCodecDecoder)
        assert decoder.name == "nvvideocodec"

    def test_falls_back_to_cpu_when_gpu_unavailable(self):
        """When GPU deps are not installed, should still return a CPU decoder."""
        from services.video_decoder import get_best_decoder

        # GPU deps are not installed, so it should fall back
        decoder = get_best_decoder()
        # Should be PyAV or FFmpeg, not GPU
        assert decoder.name in ("pyav", "ffmpeg")

    @patch("services.gpu_decoder._nvcodec_available", False)
    @patch.dict("sys.modules", {"av": MagicMock()})
    def test_falls_back_to_pyav_when_gpu_unavailable(self):
        from services.video_decoder import PyAVDecoder, get_best_decoder

        decoder = get_best_decoder()
        assert isinstance(decoder, PyAVDecoder)

    @patch(
        "services.video_decoder.PyAVDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    @patch(
        "services.video_decoder.FFmpegSubprocessDecoder.is_available",
        new_callable=lambda: property(lambda self: False),
    )
    def test_raises_when_nothing_available(self, _ffmpeg, _pyav):
        """When GPU, PyAV, and FFmpeg are all unavailable, should raise."""
        from services.video_decoder import get_best_decoder

        with pytest.raises(RuntimeError, match="No video decoder available"):
            get_best_decoder()
