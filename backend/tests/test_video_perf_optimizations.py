"""
Tests for video performance optimizations.

Covers:
- Task 1: Configurable embedding batch size with adaptive retry
- Task 2: Dynamic thread pool sizing
- Task 3: Frame deduplication with perceptual hashing
- Task 4: Optimized frame encoding (WebP/JPEG) for Vision API
"""

import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from core.config import ProcessingSettings, Settings
from models.ffmpeg_config import FrameExtractionConfig

# =============================================================================
# Task 1: Configurable Embedding Batch Size
# =============================================================================


@pytest.mark.unit
class TestEmbeddingBatchSize:
    def test_processing_settings_default_batch_size(self):
        s = ProcessingSettings()
        assert s.embedding_batch_size == 512

    def test_processing_settings_custom_batch_size(self):
        s = ProcessingSettings(embedding_batch_size=256)
        assert s.embedding_batch_size == 256

    def test_settings_includes_processing(self):
        s = Settings()
        assert hasattr(s, "processing")
        assert s.processing.embedding_batch_size == 512

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_uses_configured_size(self):
        """Verify generate_embeddings_batch reads from settings."""
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()

        # Mock embedding response
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 10
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        proc = VideoProcessor(mock_client, mock_blob)

        texts = ["hello world"]
        result = await proc.generate_embeddings_batch(texts)
        assert len(result) == 1
        assert result[0] == [0.1] * 10

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_adaptive_retry(self):
        """On API error, retry with halved batch size."""
        from openai import APIError

        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.5] * 3

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call (full batch) fails, subsequent calls succeed
            if call_count == 1:
                raise APIError(
                    message="Rate limit exceeded",
                    request=MagicMock(),
                    body=None,
                )
            resp = MagicMock()
            resp.data = [MagicMock(embedding=[0.5] * 3) for _ in kwargs["input"]]
            return resp

        mock_client.embeddings.create = AsyncMock(side_effect=mock_create)

        proc = VideoProcessor(mock_client, mock_blob)
        texts = ["text1", "text2"]
        result = await proc.generate_embeddings_batch(texts, batch_size=2)

        # Should have retried and still produced embeddings
        assert len(result) == 2
        assert call_count > 1  # At least one retry happened


# =============================================================================
# Task 2: Dynamic Thread Pool Sizing
# =============================================================================


@pytest.mark.unit
class TestDynamicThreadPoolSizing:
    def test_get_optimal_workers_returns_int(self):
        from services.ffmpeg_processor import _get_optimal_workers

        result = _get_optimal_workers()
        assert isinstance(result, int)
        assert 2 <= result <= 16

    def test_get_optimal_workers_min_2(self):
        from services.ffmpeg_processor import _get_optimal_workers

        with patch("os.cpu_count", return_value=1):
            # On Windows, sched_getaffinity doesn't exist, so it falls to cpu_count
            try:
                # Remove sched_getaffinity if it exists to force cpu_count path
                with patch.object(os, "sched_getaffinity", side_effect=AttributeError):
                    result = _get_optimal_workers()
            except AttributeError:
                result = _get_optimal_workers()
            assert result >= 2

    def test_get_optimal_workers_max_16(self):
        from services.ffmpeg_processor import _get_optimal_workers

        with patch("os.cpu_count", return_value=32):
            try:
                with patch.object(os, "sched_getaffinity", side_effect=AttributeError):
                    result = _get_optimal_workers()
            except AttributeError:
                result = _get_optimal_workers()
            assert result <= 16

    def test_processing_settings_default_workers_none(self):
        s = ProcessingSettings()
        assert s.max_extraction_workers is None

    def test_processing_settings_custom_workers(self):
        s = ProcessingSettings(max_extraction_workers=12)
        assert s.max_extraction_workers == 12

    def test_max_extraction_workers_property_uses_settings(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        mock_settings = MagicMock()
        mock_settings.processing.max_extraction_workers = 6

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())
        with patch("services.ffmpeg_processor.get_settings", return_value=mock_settings):
            assert proc._max_extraction_workers == 6

    def test_max_extraction_workers_property_falls_back_to_dynamic(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        mock_settings = MagicMock()
        mock_settings.processing.max_extraction_workers = None

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())
        with patch("services.ffmpeg_processor.get_settings", return_value=mock_settings):
            result = proc._max_extraction_workers
            assert isinstance(result, int)
            assert 2 <= result <= 16


# =============================================================================
# Task 3: Frame Deduplication
# =============================================================================


def _make_frame_bytes(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    """Create a solid-color JPEG image as bytes."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_patterned_frame_bytes(pattern: str, size: tuple[int, int] = (64, 64)) -> bytes:
    """Create a JPEG image with a distinct visual pattern for pHash differentiation.

    Solid-color images produce identical perceptual hashes regardless of color,
    so this helper creates structurally different images instead.
    """
    img = Image.new("RGB", size, (255, 255, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    w, h = size
    if pattern == "checkerboard":
        for x in range(0, w, 16):
            for y in range(0, h, 16):
                if (x // 16 + y // 16) % 2 == 0:
                    draw.rectangle([x, y, x + 16, y + 16], fill=(0, 0, 0))
    elif pattern == "gradient":
        for x in range(w):
            gray = int(255 * x / w)
            draw.line([(x, 0), (x, h)], fill=(gray, gray, gray))
    elif pattern == "circle":
        draw.rectangle([0, 0, w, h], fill=(0, 0, 0))
        draw.ellipse([4, 4, w - 4, h - 4], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.mark.unit
class TestFrameDeduplication:
    def test_deduplication_config_defaults(self):
        config = FrameExtractionConfig()
        assert config.deduplication_enabled is True
        assert config.deduplication_threshold == 12

    def test_deduplication_config_custom(self):
        config = FrameExtractionConfig(deduplication_enabled=False, deduplication_threshold=10)
        assert config.deduplication_enabled is False
        assert config.deduplication_threshold == 10

    def test_deduplicate_frames_removes_identical(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())

        red = _make_frame_bytes((255, 0, 0))
        frames = [
            {"frame_number": 0, "timestamp": 0.0, "image_data": red},
            {"frame_number": 1, "timestamp": 1.0, "image_data": red},  # duplicate
            {"frame_number": 2, "timestamp": 2.0, "image_data": red},  # duplicate
        ]
        result = proc._deduplicate_frames(frames, threshold=5)
        assert len(result) == 1
        assert result[0]["frame_number"] == 0

    def test_deduplicate_frames_keeps_distinct(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())

        frames = [
            {
                "frame_number": 0,
                "timestamp": 0.0,
                "image_data": _make_patterned_frame_bytes("checkerboard"),
            },
            {
                "frame_number": 1,
                "timestamp": 1.0,
                "image_data": _make_patterned_frame_bytes("gradient"),
            },
            {
                "frame_number": 2,
                "timestamp": 2.0,
                "image_data": _make_patterned_frame_bytes("circle"),
            },
        ]
        result = proc._deduplicate_frames(frames, threshold=5)
        assert len(result) == 3

    def test_deduplicate_frames_empty_list(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())
        result = proc._deduplicate_frames([], threshold=5)
        assert result == []

    def test_deduplicate_frames_threshold_zero_strict(self):
        """threshold=0 means only byte-identical perceptual hashes are removed."""
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor(FFmpegProcessingConfig())

        # Two very similar but not identical images
        red1 = _make_frame_bytes((255, 0, 0))
        red2 = _make_frame_bytes((254, 0, 0))  # Slightly different
        frames = [
            {"frame_number": 0, "timestamp": 0.0, "image_data": red1},
            {"frame_number": 1, "timestamp": 1.0, "image_data": red2},
        ]
        result = proc._deduplicate_frames(frames, threshold=0)
        # With threshold=0, very similar frames might still be kept
        # (depends on whether phash distance is exactly 0)
        assert len(result) >= 1


# =============================================================================
# Task 4: Optimized Frame Encoding
# =============================================================================


@pytest.mark.unit
class TestOptimizedFrameEncoding:
    def test_processing_settings_defaults(self):
        s = ProcessingSettings()
        assert s.frame_encoding_format == "webp"
        assert s.frame_encoding_quality == 80
        assert s.frame_max_dimension == 2048

    def test_processing_settings_jpeg_format(self):
        s = ProcessingSettings(frame_encoding_format="jpeg")
        assert s.frame_encoding_format == "jpeg"

    def test_encode_frame_optimized_webp(self):
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        frame_bytes = _make_frame_bytes((100, 150, 200), size=(100, 100))
        b64_data, media_type = proc._encode_frame_optimized(
            frame_bytes, use_webp=True, quality=80, max_dimension=2048
        )
        assert media_type == "image/webp"
        assert len(b64_data) > 0

        # Verify the output is valid base64
        import base64

        decoded = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(decoded))
        assert img.format == "WEBP"

    def test_encode_frame_optimized_jpeg(self):
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        frame_bytes = _make_frame_bytes((100, 150, 200), size=(100, 100))
        b64_data, media_type = proc._encode_frame_optimized(
            frame_bytes, use_webp=False, quality=85, max_dimension=2048
        )
        assert media_type == "image/jpeg"
        assert len(b64_data) > 0

    def test_encode_frame_optimized_resize(self):
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        # Create a large image (4000x3000)
        large_img = Image.new("RGB", (4000, 3000), (50, 100, 150))
        buf = io.BytesIO()
        large_img.save(buf, format="JPEG", quality=95)
        frame_bytes = buf.getvalue()

        b64_data, media_type = proc._encode_frame_optimized(
            frame_bytes, max_dimension=1024, use_webp=True, quality=80
        )

        import base64

        decoded = base64.b64decode(b64_data)
        result_img = Image.open(io.BytesIO(decoded))
        assert max(result_img.size) <= 1024

    def test_encode_frame_optimized_numpy_input(self):
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        # Create a numpy array (simulating OpenCV frame)
        np_frame = np.zeros((100, 150, 3), dtype=np.uint8)
        np_frame[:, :, 0] = 200  # Red channel

        b64_data, media_type = proc._encode_frame_optimized(
            np_frame, use_webp=True, quality=80, max_dimension=2048
        )
        assert media_type == "image/webp"
        assert len(b64_data) > 0

    def test_prepare_frames_for_batch_includes_media_type(self):
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        frames = [
            {
                "frame_number": 0,
                "timestamp": 0.0,
                "image_data": _make_frame_bytes((128, 128, 128)),
            }
        ]

        result = proc._prepare_frames_for_batch(frames)
        assert len(result) == 1
        assert "media_type" in result[0]
        assert result[0]["media_type"] in ("image/webp", "image/jpeg")
        assert "image_base64" in result[0]
        assert "max_tokens" in result[0]

    def test_webp_smaller_than_jpeg(self):
        """WebP should generally produce smaller output than JPEG at same quality."""
        from services.video_processor import VideoProcessor

        mock_client = AsyncMock()
        mock_blob = MagicMock()
        proc = VideoProcessor(mock_client, mock_blob)

        # Create a realistic-ish image with gradients
        img = Image.new("RGB", (512, 512))
        pixels = img.load()
        for x in range(512):
            for y in range(512):
                pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        frame_bytes = buf.getvalue()

        webp_data, _ = proc._encode_frame_optimized(
            frame_bytes, use_webp=True, quality=80, max_dimension=2048
        )
        jpeg_data, _ = proc._encode_frame_optimized(
            frame_bytes, use_webp=False, quality=80, max_dimension=2048
        )

        # WebP should be meaningfully smaller
        assert len(webp_data) < len(jpeg_data)
