"""Tests for the streaming video-processing pipeline.

Covers:
- ``ProcessingSettings`` streaming configuration defaults
- ``FFmpegVideoProcessor.extract_frames_stream`` async generator
- ``FFmpegVideoProcessor._pyav_frame_generator`` sync generator
- ``VideoProcessor._process_frames_streaming`` batching consumer
"""

from __future__ import annotations

from fractions import Fraction
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_av_frame(
    width: int = 64,
    height: int = 48,
    pts: int = 0,
    time_base=None,
):
    """Return a mock ``av.VideoFrame``-like object."""
    if time_base is None:
        time_base = Fraction(1, 1000)
    frame = MagicMock()
    frame.pts = pts
    frame.width = width
    frame.height = height

    def _to_ndarray(format="rgb24"):  # noqa: A002
        return np.zeros((height, width, 3), dtype=np.uint8)

    frame.to_ndarray = _to_ndarray
    return frame


def _make_frame_dict(frame_number: int, timestamp: float = 0.0) -> dict:
    """Create a minimal frame dict as yielded by extract_frames_stream."""
    # 2×2 black JPEG is the smallest valid JPEG we can create cheaply
    import io

    from PIL import Image

    img = Image.new("RGB", (2, 2), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return {
        "frame_number": frame_number,
        "timestamp": timestamp,
        "image_data": buf.getvalue(),
        "metadata": {"width": 2, "height": 2, "extraction_mode": "test"},
    }


# ---------------------------------------------------------------------------
# ProcessingSettings streaming defaults
# ---------------------------------------------------------------------------


class TestStreamingConfig:
    def test_streaming_disabled_by_default(self):
        from core.config import ProcessingSettings

        s = ProcessingSettings()
        assert s.streaming_pipeline_enabled is False

    def test_streaming_batch_size_default(self):
        from core.config import ProcessingSettings

        s = ProcessingSettings()
        assert s.streaming_batch_size == 32

    def test_streaming_can_be_enabled(self):
        from core.config import ProcessingSettings

        s = ProcessingSettings(
            streaming_pipeline_enabled=True,
            streaming_batch_size=16,
        )
        assert s.streaming_pipeline_enabled is True
        assert s.streaming_batch_size == 16


# ---------------------------------------------------------------------------
# _pyav_frame_generator  (synchronous generator)
# ---------------------------------------------------------------------------


class TestPyavFrameGenerator:
    """Test the sync generator that wraps PyAV sequential decode."""

    @patch("services.pyav_extractor._AV_AVAILABLE", False)
    def test_returns_nothing_when_pyav_missing(self):
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = FFmpegProcessingConfig()
        proc._decoder_backend = "pyav"

        gen = proc._pyav_frame_generator("dummy.mp4", {"duration": 10, "fps": 30})
        assert list(gen) == []

    @patch("services.pyav_extractor._AV_AVAILABLE", True)
    @patch("services.pyav_extractor._open_container")
    def test_yields_frames_at_target_timestamps(self, mock_open):
        """Sequential decode should yield frames matching target timestamps."""
        from models.ffmpeg_config import (
            FFmpegProcessingConfig,
            FrameExtractionConfig,
            FrameExtractionMethod,
        )
        from services.ffmpeg_processor import FFmpegVideoProcessor
        from services.timestamp_calculator import TimestampCalculator

        # Build processor with UNIFORM method, 2 frames over 2s video
        config = FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.UNIFORM,
                num_frames=2,
                max_frames=10,
            )
        )
        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = config
        proc._decoder_backend = "pyav"
        proc._use_pyscenedetect = False
        proc._timestamp_calculator = TimestampCalculator()

        # Mock container that yields frames at pts 0, 500, 1000, 1500, 2000
        time_base = Fraction(1, 1000)
        av_frames = [_fake_av_frame(pts=i * 500, time_base=time_base) for i in range(5)]

        stream = MagicMock()
        stream.time_base = time_base
        stream.average_rate = 30
        stream.thread_type = None

        container = MagicMock()
        container.streams.video = [stream]
        container.decode = MagicMock(return_value=iter(av_frames))
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = container

        video_info = {"duration": 2.0, "fps": 30, "width": 64, "height": 48}
        results = list(proc._pyav_frame_generator("test.mp4", video_info))

        assert len(results) == 2
        for r in results:
            assert "image_data" in r
            assert "timestamp" in r
            assert "frame_number" in r
            assert "metadata" in r
            assert r["metadata"]["extraction_mode"] == "streaming_pyav"


# ---------------------------------------------------------------------------
# extract_frames_stream  (async generator)
# ---------------------------------------------------------------------------


class TestExtractFramesStream:
    @pytest.mark.asyncio
    async def test_fallback_when_pyav_unavailable(self):
        """When pyav is not the backend, fall back to batch + yield."""
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = FFmpegProcessingConfig()
        proc._decoder_backend = "ffmpeg_subprocess"
        proc.status = MagicMock()

        dummy_frames = [_make_frame_dict(i, float(i)) for i in range(3)]

        with (
            patch.object(
                proc,
                "get_video_info",
                return_value={"duration": 5, "fps": 30, "width": 64, "height": 48},
            ),
            patch.object(
                proc,
                "extract_frames_ffmpeg",
                return_value=dummy_frames,
            ),
        ):
            collected: list[dict] = []
            async for frame in proc.extract_frames_stream("test.mp4"):
                collected.append(frame)

        assert len(collected) == 3
        assert collected[0]["frame_number"] == 0
        assert collected[2]["frame_number"] == 2

    @pytest.mark.asyncio
    async def test_pyav_path_yields_frames(self):
        """When PyAV backend succeeds, frames are streamed via the generator."""
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = FFmpegProcessingConfig()
        proc._decoder_backend = "pyav"
        proc.status = MagicMock()

        fake_frames = [_make_frame_dict(i, float(i)) for i in range(4)]

        # Mock _pyav_frame_generator as a regular generator
        with (
            patch.object(
                proc,
                "get_video_info",
                return_value={"duration": 5, "fps": 30, "width": 64, "height": 48},
            ),
            patch.object(
                proc,
                "_pyav_frame_generator",
                return_value=iter(fake_frames),
            ),
        ):
            collected: list[dict] = []
            async for frame in proc.extract_frames_stream("test.mp4"):
                collected.append(frame)

        assert len(collected) == 4

    @pytest.mark.asyncio
    async def test_max_frames_respected(self):
        """Streaming should stop after max_frames."""
        from models.ffmpeg_config import (
            FFmpegProcessingConfig,
            FrameExtractionConfig,
        )
        from services.ffmpeg_processor import FFmpegVideoProcessor

        config = FFmpegProcessingConfig(frame_extraction=FrameExtractionConfig(max_frames=2))
        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = config
        proc._decoder_backend = "pyav"
        proc.status = MagicMock()

        # Generator produces 10 frames, but max_frames=2
        fake_frames = [_make_frame_dict(i, float(i)) for i in range(10)]

        with (
            patch.object(
                proc,
                "get_video_info",
                return_value={"duration": 10, "fps": 30, "width": 64, "height": 48},
            ),
            patch.object(
                proc,
                "_pyav_frame_generator",
                return_value=iter(fake_frames),
            ),
        ):
            collected: list[dict] = []
            async for frame in proc.extract_frames_stream("test.mp4"):
                collected.append(frame)

        assert len(collected) == 2

    @pytest.mark.asyncio
    async def test_pyav_failure_triggers_fallback(self):
        """If PyAV streaming raises, fall back to batch extraction."""
        from models.ffmpeg_config import FFmpegProcessingConfig
        from services.ffmpeg_processor import FFmpegVideoProcessor

        proc = FFmpegVideoProcessor.__new__(FFmpegVideoProcessor)
        proc.config = FFmpegProcessingConfig()
        proc._decoder_backend = "pyav"
        proc.status = MagicMock()

        fallback_frames = [_make_frame_dict(0, 0.0)]

        def _broken_generator(*_a, **_kw):
            raise RuntimeError("PyAV exploded")

        with (
            patch.object(
                proc,
                "get_video_info",
                return_value={"duration": 5, "fps": 30, "width": 64, "height": 48},
            ),
            patch.object(
                proc,
                "_pyav_frame_generator",
                side_effect=_broken_generator,
            ),
            patch.object(
                proc,
                "extract_frames_ffmpeg",
                return_value=fallback_frames,
            ),
        ):
            collected: list[dict] = []
            async for frame in proc.extract_frames_stream("test.mp4"):
                collected.append(frame)

        assert len(collected) == 1
        assert collected[0]["frame_number"] == 0


# ---------------------------------------------------------------------------
# _process_frames_streaming  (batching consumer)
# ---------------------------------------------------------------------------


class TestProcessFramesStreaming:
    """Test the streaming consumer in VideoProcessor."""

    def _make_processor(self) -> MagicMock:
        """Create a minimal mock VideoProcessor with real streaming method."""
        from services.video_processor import VideoProcessor

        proc = MagicMock(spec=VideoProcessor)
        # Bind the real streaming method
        proc._process_frames_streaming = VideoProcessor._process_frames_streaming.__get__(proc)

        # Mock _prepare_frames_for_batch to return predictable output
        # without depending on PIL / settings / _encode_frame_optimized
        def _mock_prepare(frames):
            return [
                {
                    "frame_number": f["frame_number"],
                    "timestamp": f.get("timestamp"),
                    "image_base64": "base64data",
                    "media_type": "image/jpeg",
                    "max_tokens": 600,
                }
                for f in frames
            ]

        proc._prepare_frames_for_batch = _mock_prepare
        return proc

    @pytest.mark.asyncio
    async def test_processes_all_frames(self):
        proc = self._make_processor()
        frames = [_make_frame_dict(i, float(i)) for i in range(5)]

        async def _stream():
            for f in frames:
                yield f

        count, prepared = await proc._process_frames_streaming(_stream())

        assert count == 5
        assert len(prepared) == 5
        # Each prepared frame should have image_base64 and max_tokens
        for p in prepared:
            assert "image_base64" in p
            assert "max_tokens" in p
            assert isinstance(p["max_tokens"], int)

    @pytest.mark.asyncio
    async def test_batching_respects_batch_size(self):
        """With batch_size=3 and 7 frames, we should see 3 batches."""
        proc = self._make_processor()
        frames = [_make_frame_dict(i, float(i)) for i in range(7)]

        batch_call_count = 0
        original_prepare = proc._prepare_frames_for_batch

        def _counting_prepare(batch):
            nonlocal batch_call_count
            batch_call_count += 1
            return original_prepare(batch)

        proc._prepare_frames_for_batch = _counting_prepare

        async def _stream():
            for f in frames:
                yield f

        count, prepared = await proc._process_frames_streaming(_stream(), batch_size=3)

        assert count == 7
        assert len(prepared) == 7
        # 7 frames / batch_size 3 → batches of 3, 3, 1
        assert batch_call_count == 3

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        proc = self._make_processor()

        async def _stream():
            return
            yield  # noqa: RET504 — make this an async generator

        count, prepared = await proc._process_frames_streaming(_stream())

        assert count == 0
        assert prepared == []

    @pytest.mark.asyncio
    async def test_single_frame(self):
        proc = self._make_processor()
        frames = [_make_frame_dict(0, 0.0)]

        async def _stream():
            for f in frames:
                yield f

        count, prepared = await proc._process_frames_streaming(_stream(), batch_size=10)

        assert count == 1
        assert len(prepared) == 1
