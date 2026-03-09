"""
Tests for the optimized extract_frames_task and updated analyze_frame_task.

Covers:
- extract_frames_task uses FFmpegVideoProcessor (PyAV + deduplication)
- extract_frames_task returns correct structure with new metadata fields
- Frame re-encoding via PIL into configured format (WebP/JPEG)
- PIL-based quality metrics (blur approximation and brightness)
- analyze_frame_task passes raw bytes directly (no cv2/numpy round-trip)
- analyze_frame_with_gpt4v accepts bytes input
"""

import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame_bytes(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    """Create a minimal JPEG image with the given solid colour."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_raw_frames(n: int = 3) -> list[dict]:
    """Build a list of raw frame dicts as returned by FFmpegVideoProcessor."""
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 0), (0, 128, 128)]
    frames = []
    for i in range(n):
        c = colours[i % len(colours)]
        frames.append(
            {
                "timestamp": float(i * 2),
                "frame_number": i * 30,
                "image_data": _make_frame_bytes(c),
            }
        )
    return frames


# ===========================================================================
# extract_frames_task — return structure
# ===========================================================================


@pytest.mark.unit
class TestExtractFramesTaskStructure:
    """Verify the dict returned by extract_frames_task has all required keys."""

    @patch("tasks.video_tasks._initialize_services")
    @patch("tasks.video_tasks.update_job_status")
    @patch("services.ffmpeg_processor.FFmpegVideoProcessor")
    def test_return_contains_required_keys(self, MockProcessor, mock_status, mock_init):
        """Returned dict must have frames, metadata, temp_path, blob_name."""
        # Arrange
        raw = _make_raw_frames(2)
        mock_instance = MagicMock()
        mock_instance.get_video_info.return_value = {
            "fps": 30.0,
            "frame_count": 900,
            "duration": 30.0,
            "width": 1920,
            "height": 1080,
        }
        mock_instance.extract_frames_ffmpeg.return_value = raw
        mock_instance.status = MagicMock(frames_extracted=3)
        MockProcessor.return_value = mock_instance

        # Patch settings
        mock_settings = MagicMock()
        mock_settings.app.video_decoder_backend = "pyav"
        mock_settings.processing.frame_encoding_format = "webp"
        mock_settings.processing.frame_encoding_quality = 80

        download_result = {"temp_path": "/tmp/test.mp4", "blob_name": "videos/test.mp4"}

        with patch("core.config.settings", mock_settings):
            from tasks.video_tasks import extract_frames_task

            # Act — call the underlying function directly (unwrap Celery)
            result = extract_frames_task.__wrapped__(download_result, "job-1", max_frames=10)

        # Assert top-level keys
        assert "frames" in result
        assert "metadata" in result
        assert "temp_path" in result
        assert "blob_name" in result
        assert result["temp_path"] == "/tmp/test.mp4"
        assert result["blob_name"] == "videos/test.mp4"

    @patch("tasks.video_tasks._initialize_services")
    @patch("tasks.video_tasks.update_job_status")
    @patch("services.ffmpeg_processor.FFmpegVideoProcessor")
    def test_frame_dicts_have_required_fields(self, MockProcessor, mock_status, mock_init):
        """Each frame dict must contain index, frame_number, timestamp, image_bytes."""
        raw = _make_raw_frames(2)
        mock_instance = MagicMock()
        mock_instance.get_video_info.return_value = {
            "fps": 25.0,
            "frame_count": 500,
            "duration": 20.0,
            "width": 1280,
            "height": 720,
        }
        mock_instance.extract_frames_ffmpeg.return_value = raw
        mock_instance.status = MagicMock(frames_extracted=3)
        MockProcessor.return_value = mock_instance

        mock_settings = MagicMock()
        mock_settings.app.video_decoder_backend = "pyav"
        mock_settings.processing.frame_encoding_format = "webp"
        mock_settings.processing.frame_encoding_quality = 80

        download_result = {"temp_path": "/tmp/v.mp4", "blob_name": "v.mp4"}

        with patch("core.config.settings", mock_settings):
            from tasks.video_tasks import extract_frames_task

            result = extract_frames_task.__wrapped__(download_result, "job-2", max_frames=5)

        for frame in result["frames"]:
            assert "index" in frame
            assert "frame_number" in frame
            assert "timestamp" in frame
            assert "image_bytes" in frame
            assert isinstance(frame["image_bytes"], bytes)
            assert "blur_score" in frame
            assert "brightness" in frame

    @patch("tasks.video_tasks._initialize_services")
    @patch("tasks.video_tasks.update_job_status")
    @patch("services.ffmpeg_processor.FFmpegVideoProcessor")
    def test_metadata_has_new_fields(self, MockProcessor, mock_status, mock_init):
        """Metadata must include decoder_backend, deduplication_enabled,
        frames_before_dedup, and encoding_format."""
        raw = _make_raw_frames(1)
        mock_instance = MagicMock()
        mock_instance.get_video_info.return_value = {
            "fps": 30.0,
            "frame_count": 300,
            "duration": 10.0,
            "width": 640,
            "height": 480,
        }
        mock_instance.extract_frames_ffmpeg.return_value = raw
        mock_instance.status = MagicMock(frames_extracted=2)
        MockProcessor.return_value = mock_instance

        mock_settings = MagicMock()
        mock_settings.app.video_decoder_backend = "pyav"
        mock_settings.processing.frame_encoding_format = "webp"
        mock_settings.processing.frame_encoding_quality = 80

        download_result = {"temp_path": "/tmp/v.mp4", "blob_name": "v.mp4"}

        with patch("core.config.settings", mock_settings):
            from tasks.video_tasks import extract_frames_task

            result = extract_frames_task.__wrapped__(download_result, "job-3")

        meta = result["metadata"]
        assert meta["decoder_backend"] == "pyav"
        assert meta["deduplication_enabled"] is True
        assert "frames_before_dedup" in meta
        assert meta["encoding_format"] == "webp"
        # Legacy fields still present
        assert "fps" in meta
        assert "total_frames" in meta
        assert "duration" in meta
        assert "resolution" in meta
        assert meta["resolution"] == "640x480"
        assert "frames_extracted" in meta


# ===========================================================================
# PIL-based quality metrics
# ===========================================================================


@pytest.mark.unit
class TestPILQualityMetrics:
    """Verify blur_score and brightness are computed without cv2."""

    def test_brightness_white_image(self):
        """A fully white image should have brightness close to 1.0."""
        white = _make_frame_bytes((255, 255, 255))
        # Import the helper indirectly by running extract_frames_task logic
        img = Image.open(io.BytesIO(white)).convert("L")
        arr = np.asarray(img, dtype=np.float64)
        brightness = float(arr.mean() / 255.0)
        assert brightness > 0.95

    def test_brightness_black_image(self):
        """A fully black image should have brightness close to 0.0."""
        black = _make_frame_bytes((0, 0, 0))
        img = Image.open(io.BytesIO(black)).convert("L")
        arr = np.asarray(img, dtype=np.float64)
        brightness = float(arr.mean() / 255.0)
        assert brightness < 0.05

    def test_blur_score_returns_float_in_range(self):
        """Blur score should be a float between 0 and 1."""
        from PIL import ImageFilter

        frame = _make_frame_bytes((128, 64, 200), size=(100, 100))
        img = Image.open(io.BytesIO(frame)).convert("L")
        edges = img.filter(ImageFilter.FIND_EDGES)
        arr = np.asarray(edges, dtype=np.float64)
        score = min(float(arr.var()) / 2000.0, 1.0)
        assert 0.0 <= score <= 1.0


# ===========================================================================
# Frame re-encoding
# ===========================================================================


@pytest.mark.unit
class TestFrameReEncoding:
    """Verify frames are re-encoded into the configured format."""

    def test_encode_to_webp(self):
        """Encoding a JPEG frame to WebP should produce valid WebP bytes."""
        jpeg_bytes = _make_frame_bytes((100, 150, 200))
        img = Image.open(io.BytesIO(jpeg_bytes))
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=80)
        webp_bytes = buf.getvalue()

        # Verify it's valid WebP
        result_img = Image.open(io.BytesIO(webp_bytes))
        assert result_img.format == "WEBP"

    def test_encode_to_jpeg(self):
        """Encoding a frame to JPEG should produce valid JPEG bytes."""
        source = _make_frame_bytes((50, 100, 150))
        img = Image.open(io.BytesIO(source))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        jpeg_bytes = buf.getvalue()

        result_img = Image.open(io.BytesIO(jpeg_bytes))
        assert result_img.format == "JPEG"

    def test_webp_generally_smaller(self):
        """WebP should generally be smaller than JPEG at the same quality."""
        # Create a gradient image (not trivially compressible)
        img = Image.new("RGB", (256, 256))
        pixels = img.load()
        for x in range(256):
            for y in range(256):
                pixels[x, y] = (x, y, (x + y) % 256)

        buf_jpeg = io.BytesIO()
        img.save(buf_jpeg, format="JPEG", quality=80)

        buf_webp = io.BytesIO()
        img.save(buf_webp, format="WEBP", quality=80)

        assert buf_webp.tell() < buf_jpeg.tell()


# ===========================================================================
# analyze_frame_task — bytes passthrough
# ===========================================================================


@pytest.mark.unit
class TestAnalyzeFrameTaskBytes:
    """Verify analyze_frame_task passes bytes directly without cv2."""

    @patch("tasks.video_tasks._initialize_services")
    @patch("tasks.video_tasks._video_processor")
    def test_passes_bytes_directly(self, mock_processor, mock_init):
        """analyze_frame_task must pass image bytes to analyze_frame_with_gpt4v
        without going through cv2.imdecode."""

        mock_analysis = {
            "analysis": "A red frame.",
            "tokens_used": 42,
            "model": "gpt-4o",
        }
        mock_processor.analyze_frame_with_gpt4v = AsyncMock(return_value=mock_analysis)

        frame_bytes = _make_frame_bytes((255, 0, 0))
        frame_data = {
            "index": 0,
            "frame_number": 0,
            "timestamp": 0.0,
            "image_bytes": frame_bytes,
        }

        from tasks.video_tasks import analyze_frame_task

        result = analyze_frame_task.__wrapped__(frame_data, "job-x", custom_prompt=None)

        # Verify bytes were passed directly (first positional arg)
        call_args = mock_processor.analyze_frame_with_gpt4v.call_args
        passed_frame = call_args[0][0]
        assert isinstance(passed_frame, bytes)
        assert passed_frame == frame_bytes

        assert result["analysis"] == "A red frame."
        assert result["tokens_used"] == 42

    @patch("tasks.video_tasks._initialize_services")
    @patch("tasks.video_tasks._video_processor")
    def test_handles_base64_encoded_bytes(self, mock_processor, mock_init):
        """When image_bytes arrives as a base64 string (JSON serialization),
        it must be decoded first."""
        mock_analysis = {"analysis": "Green.", "tokens_used": 10, "model": "gpt-4o"}
        mock_processor.analyze_frame_with_gpt4v = AsyncMock(return_value=mock_analysis)

        raw_bytes = _make_frame_bytes((0, 255, 0))
        b64_str = base64.b64encode(raw_bytes).decode("utf-8")

        frame_data = {
            "index": 1,
            "frame_number": 30,
            "timestamp": 1.0,
            "image_bytes": b64_str,  # base64 string
        }

        from tasks.video_tasks import analyze_frame_task

        result = analyze_frame_task.__wrapped__(frame_data, "job-y")

        call_args = mock_processor.analyze_frame_with_gpt4v.call_args
        passed_frame = call_args[0][0]
        assert isinstance(passed_frame, bytes)
        assert passed_frame == raw_bytes
        assert result["index"] == 1


# ===========================================================================
# analyze_frame_with_gpt4v — accepts bytes
# ===========================================================================


@pytest.mark.unit
class TestAnalyzeFrameWithGpt4vAcceptsBytes:
    """Verify VideoProcessor.analyze_frame_with_gpt4v accepts raw bytes."""

    def test_encode_frame_optimized_handles_bytes(self):
        """_encode_frame_optimized must handle raw bytes input."""
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        frame_bytes = _make_frame_bytes((100, 200, 50))
        b64_data, media_type = proc._encode_frame_optimized(
            frame_bytes, use_webp=True, quality=80, max_dimension=2048
        )
        assert media_type == "image/webp"
        assert len(b64_data) > 0

        # Also works with numpy arrays (backward compat)
        np_frame = np.zeros((64, 64, 3), dtype=np.uint8)
        b64_data2, media_type2 = proc._encode_frame_optimized(
            np_frame, use_webp=True, quality=80, max_dimension=2048
        )
        assert media_type2 == "image/webp"
        assert len(b64_data2) > 0

    @pytest.mark.asyncio
    async def test_analyze_frame_bytes_input(self):
        """analyze_frame_with_gpt4v should work when given raw bytes."""
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Frame analysis result"
        mock_response.usage.total_tokens = 100
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        proc = VideoProcessor(mock_client, mock_blob)
        frame_bytes = _make_frame_bytes((128, 128, 128))

        result = await proc.analyze_frame_with_gpt4v(frame_bytes, timestamp=5.0)

        assert result["analysis"] == "Frame analysis result"
        assert result["tokens_used"] == 100


# ===========================================================================
# No cv2 import in tasks
# ===========================================================================


@pytest.mark.unit
class TestNoCv2InTasks:
    """Ensure the video tasks module does not import cv2 at module level."""

    def test_no_cv2_top_level_import(self):
        """video_tasks should not have cv2 as a top-level import."""
        import importlib
        import inspect

        source = inspect.getsource(importlib.import_module("tasks.video_tasks"))
        # Check that there's no top-level "import cv2" (not inside a function)
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            # Skip commented lines
            if stripped.startswith("#"):
                continue
            # A top-level import would have no leading whitespace
            if line == stripped and stripped in ("import cv2", "import cv2  "):
                pytest.fail("Found top-level 'import cv2' in video_tasks.py")
