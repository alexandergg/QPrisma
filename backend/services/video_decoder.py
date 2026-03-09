"""Unified video decoder abstraction for QPrisma.

Provides a protocol-based interface for video decoding backends,
enabling transparent backend switching and future GPU decoder support.

Existing decoder implementations are *not* modified — this module wraps
them behind a common :class:`VideoDecoder` protocol so callers can
depend on a stable, typed interface regardless of the underlying engine.

Usage::

    from services.video_decoder import get_best_decoder

    decoder = get_best_decoder()
    info = await decoder.get_video_info("movie.mp4")
    frames = await decoder.extract_frames("movie.mp4", max_frames=10)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoInfo:
    """Container for video metadata.

    Field names are normalised across backends — callers never need to
    know whether the info came from PyAV or ffprobe.
    """

    width: int
    height: int
    fps: float
    duration: float
    total_frames: int
    codec: str = ""
    pixel_format: str = ""


@dataclass(frozen=True)
class ExtractedFrame:
    """Container for a single extracted frame.

    ``image_data`` holds raw JPEG bytes ready for storage / vision API
    consumption.  ``metadata`` is reserved for decoder-specific extras
    (e.g. keyframe flag, phash).
    """

    image_data: bytes
    timestamp: float
    frame_number: int
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VideoDecoder(Protocol):
    """Protocol for video decoder backends.

    Implementations:
    - :class:`PyAVDecoder` — C-level FFmpeg bindings via PyAV (default, fastest CPU)
    - :class:`FFmpegSubprocessDecoder` — FFmpeg CLI subprocess (universal fallback)
    """

    @property
    def name(self) -> str:
        """Human-readable decoder name (e.g. ``"pyav"``, ``"ffmpeg"``)."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether this decoder's runtime dependencies are installed."""
        ...

    async def get_video_info(self, video_path: str) -> VideoInfo:
        """Return normalised metadata for *video_path*."""
        ...

    async def extract_frames(
        self,
        video_path: str,
        *,
        timestamps: list[float] | None = None,
        max_frames: int = 0,
        interval_seconds: float = 0,
        start_time: float = 0,
        end_time: float = 0,
    ) -> list[ExtractedFrame]:
        """Extract frames from a video file.

        Callers may specify *which* frames to extract via one of:

        * ``timestamps`` — explicit seek points (seconds).
        * ``max_frames`` — uniformly sample *N* frames across the file.
        * ``interval_seconds`` — one frame every *N* seconds.

        ``start_time`` / ``end_time`` optionally restrict the time range.
        """
        ...


# ---------------------------------------------------------------------------
# PyAV implementation
# ---------------------------------------------------------------------------


class PyAVDecoder:
    """Video decoder using PyAV (C-level FFmpeg bindings).

    Wraps :class:`services.pyav_extractor.PyAVFrameExtractor` behind the
    :class:`VideoDecoder` protocol.  All CPU-bound work is dispatched to
    a thread via :func:`asyncio.to_thread`.
    """

    def __init__(self) -> None:
        self._extractor: Any = None

    # -- Protocol properties -------------------------------------------------

    @property
    def name(self) -> str:
        return "pyav"

    @property
    def is_available(self) -> bool:
        try:
            import av  # noqa: F401

            return True
        except ImportError:
            return False

    # -- Lazy extractor accessor ---------------------------------------------

    def _get_extractor(self) -> Any:
        """Lazily import and instantiate ``PyAVFrameExtractor``."""
        if self._extractor is None:
            from services.pyav_extractor import PyAVFrameExtractor

            self._extractor = PyAVFrameExtractor()
        return self._extractor

    # -- Protocol methods ----------------------------------------------------

    async def get_video_info(self, video_path: str) -> VideoInfo:
        ext = self._get_extractor()
        info: dict[str, Any] = await asyncio.to_thread(ext.get_video_info, video_path)
        if not info:
            raise RuntimeError(f"PyAV could not read video info for: {video_path}")
        return VideoInfo(
            width=info.get("width", 0),
            height=info.get("height", 0),
            fps=info.get("fps", 0.0),
            duration=info.get("duration", 0.0),
            total_frames=info.get("total_frames", 0),
            codec=info.get("codec", ""),
            pixel_format="",  # PyAVFrameExtractor doesn't expose pix_fmt
        )

    async def extract_frames(
        self,
        video_path: str,
        *,
        timestamps: list[float] | None = None,
        max_frames: int = 0,
        interval_seconds: float = 0,
        start_time: float = 0,
        end_time: float = 0,
    ) -> list[ExtractedFrame]:
        ext = self._get_extractor()

        # Determine the extraction strategy based on the supplied parameters.
        if timestamps:
            raw = await asyncio.to_thread(
                ext.extract_frames,
                video_path,
                timestamps,
                max_frames if max_frames > 0 else None,
            )
        elif interval_seconds > 0:
            fps = 1.0 / interval_seconds
            raw = await asyncio.to_thread(
                ext.extract_frames_fps,
                video_path,
                fps,
                max_frames if max_frames > 0 else None,
            )
        elif max_frames > 0:
            raw = await asyncio.to_thread(
                ext.extract_frames_uniform,
                video_path,
                max_frames,
            )
        else:
            # Sensible default: 10 uniformly-distributed frames
            raw = await asyncio.to_thread(
                ext.extract_frames_uniform,
                video_path,
                10,
            )

        return self._convert_raw_frames(raw)

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _convert_raw_frames(
        raw_frames: list[tuple[float, Any]],
    ) -> list[ExtractedFrame]:
        """Convert PyAV ``(timestamp, ndarray)`` tuples → :class:`ExtractedFrame`.

        Encodes each RGB numpy array to JPEG bytes via Pillow so that the
        output is immediately usable by downstream consumers (storage,
        vision APIs, etc.) without requiring OpenCV.
        """
        from PIL import Image

        results: list[ExtractedFrame] = []
        for idx, (ts, rgb_array) in enumerate(raw_frames):
            buf = io.BytesIO()
            Image.fromarray(rgb_array).save(buf, format="JPEG", quality=95)
            results.append(
                ExtractedFrame(
                    image_data=buf.getvalue(),
                    timestamp=ts,
                    frame_number=idx,
                )
            )
        return results


# ---------------------------------------------------------------------------
# FFmpeg subprocess implementation
# ---------------------------------------------------------------------------


class FFmpegSubprocessDecoder:
    """Fallback video decoder using the FFmpeg / ffprobe CLI.

    This decoder requires ``ffmpeg`` and ``ffprobe`` on ``PATH``.
    It is intentionally kept thin — the subprocess path exists as a
    universal fallback when PyAV is not installed.
    """

    @property
    def name(self) -> str:
        return "ffmpeg"

    @property
    def is_available(self) -> bool:
        return shutil.which("ffprobe") is not None and shutil.which("ffmpeg") is not None

    async def get_video_info(self, video_path: str) -> VideoInfo:
        def _probe() -> dict[str, Any]:
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(f"ffprobe failed (rc={result.returncode}) for: {video_path}")
            return json.loads(result.stdout)

        data = await asyncio.to_thread(_probe)

        video_stream: dict[str, Any] = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        fmt = data.get("format", {})

        # Parse rational frame-rate (e.g. "30000/1001")
        fps_str = video_stream.get("r_frame_rate", "0/1")
        fps_parts = fps_str.split("/")
        if len(fps_parts) == 2:
            denom = float(fps_parts[1])
            fps = float(fps_parts[0]) / denom if denom else 0.0
        else:
            fps = float(fps_parts[0]) if fps_parts[0] else 0.0

        duration = float(fmt.get("duration", 0))
        nb_frames_str = video_stream.get("nb_frames", "0")
        try:
            total_frames = int(nb_frames_str)
        except (ValueError, TypeError):
            total_frames = int(duration * fps) if fps > 0 else 0

        return VideoInfo(
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            fps=fps,
            duration=duration,
            total_frames=total_frames,
            codec=video_stream.get("codec_name", ""),
            pixel_format=video_stream.get("pix_fmt", ""),
        )

    async def extract_frames(
        self,
        video_path: str,
        *,
        timestamps: list[float] | None = None,
        max_frames: int = 0,
        interval_seconds: float = 0,
        start_time: float = 0,
        end_time: float = 0,
    ) -> list[ExtractedFrame]:
        """Extract frames via FFmpeg subprocess piping raw image data to stdout.

        This is a baseline implementation — for production workloads prefer
        :class:`PyAVDecoder` which avoids serialisation overhead.
        """
        info = await self.get_video_info(video_path)

        # Determine which timestamps to extract
        effective_ts: list[float]
        if timestamps:
            effective_ts = sorted(timestamps)
        elif interval_seconds > 0:
            effective_ts = []
            t = start_time
            limit = end_time if end_time > 0 else info.duration
            while t < limit:
                effective_ts.append(t)
                t += interval_seconds
        elif max_frames > 0:
            if max_frames == 1:
                effective_ts = [info.duration / 2.0]
            else:
                step = info.duration / (max_frames - 1)
                effective_ts = [i * step for i in range(max_frames)]
        else:
            # Default: 10 uniform frames
            step = info.duration / 9 if info.duration > 0 else 1.0
            effective_ts = [i * step for i in range(10)]

        if max_frames > 0:
            effective_ts = effective_ts[:max_frames]

        # Extract each frame via a seek + single-frame decode
        results: list[ExtractedFrame] = []
        for idx, ts in enumerate(effective_ts):
            frame_bytes = await asyncio.to_thread(self._extract_single_frame, video_path, ts)
            if frame_bytes:
                results.append(
                    ExtractedFrame(
                        image_data=frame_bytes,
                        timestamp=ts,
                        frame_number=idx,
                    )
                )
        return results

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _extract_single_frame(video_path: str, timestamp: float) -> bytes | None:
        """Seek to *timestamp* and extract a single JPEG frame via FFmpeg."""
        cmd = [
            "ffmpeg",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            "2",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as exc:
            logger.debug("FFmpeg frame extraction failed at t=%.3f: %s", timestamp, exc)
        return None


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def get_best_decoder() -> VideoDecoder:
    """Return the best available video decoder.

    Priority order::

        1. PyAV  (C-level FFmpeg bindings — fastest CPU path)
        2. FFmpeg subprocess  (universal fallback)

    Raises:
        RuntimeError: If no decoder backend is available.
    """
    pyav = PyAVDecoder()
    if pyav.is_available:
        logger.info("Using PyAV video decoder (C-level FFmpeg bindings)")
        return pyav

    ffmpeg_dec = FFmpegSubprocessDecoder()
    if ffmpeg_dec.is_available:
        logger.info("Using FFmpeg subprocess video decoder (fallback)")
        return ffmpeg_dec

    raise RuntimeError(
        "No video decoder available. Install PyAV (pip install av) " "or ensure FFmpeg is on PATH."
    )


def get_decoder_by_name(name: str) -> VideoDecoder:
    """Instantiate a specific decoder by its short name.

    Args:
        name: ``"pyav"``, ``"ffmpeg"``, or ``"ffmpeg_subprocess"``.

    Raises:
        ValueError: Unknown decoder name.
        RuntimeError: Decoder dependencies not installed.
    """
    _registry: dict[str, type[PyAVDecoder | FFmpegSubprocessDecoder]] = {
        "pyav": PyAVDecoder,
        "ffmpeg": FFmpegSubprocessDecoder,
        # Alias used in existing config / FrameExtractionConfig.decoder_backend
        "ffmpeg_subprocess": FFmpegSubprocessDecoder,
    }

    decoder_class = _registry.get(name)
    if decoder_class is None:
        raise ValueError(
            f"Unknown decoder: {name!r}. "
            f"Available: {sorted({'ffmpeg', 'ffmpeg_subprocess', 'pyav'})}"
        )

    decoder = decoder_class()
    if not decoder.is_available:
        raise RuntimeError(f"Decoder {name!r} is not available (missing dependencies)")

    return decoder
