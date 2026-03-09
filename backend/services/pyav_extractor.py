"""
PyAV Frame Extractor

In-process video frame extraction using PyAV (Python bindings for FFmpeg libraries).
Replaces subprocess-based FFmpeg calls with direct library access for lower latency,
zero serialisation overhead, and numpy-native frame output.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    import av

    _AV_AVAILABLE = True
except ImportError:
    _AV_AVAILABLE = False
    logger.warning(
        "PyAV (av) is not installed — PyAVFrameExtractor will be unavailable. "
        "Install with: pip install 'av>=16.0.0,<17.0.0'"
    )


def is_pyav_available() -> bool:
    """Return True when the ``av`` package can be imported."""
    return _AV_AVAILABLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_container(source: str | bytes, **kwargs: Any) -> av.container.InputContainer:
    """Open an ``av.InputContainer`` from a file path or in-memory bytes."""
    if isinstance(source, bytes | bytearray | memoryview):
        return av.open(io.BytesIO(source), **kwargs)
    return av.open(source, **kwargs)


def _frame_to_rgb_ndarray(frame: av.VideoFrame) -> np.ndarray:
    """Convert an ``av.VideoFrame`` to a uint8 RGB numpy array (H×W×3)."""
    return frame.to_ndarray(format="rgb24")


# ---------------------------------------------------------------------------
# PyAVFrameExtractor
# ---------------------------------------------------------------------------


class PyAVFrameExtractor:
    """Stateless video frame extractor backed by PyAV.

    All public methods are **synchronous** and CPU-bound.  In async contexts
    callers should wrap them with ``asyncio.to_thread()``.
    """

    # ------------------------------------------------------------------
    # Video metadata
    # ------------------------------------------------------------------

    @staticmethod
    def get_video_info(source: str | bytes) -> dict[str, Any]:
        """Return metadata for a video source.

        Keys returned:
        ``duration``, ``width``, ``height``, ``fps``, ``codec``,
        ``total_frames``, ``audio_streams``.
        """
        if not _AV_AVAILABLE:
            logger.error("PyAV not available — cannot get video info")
            return {}

        try:
            with _open_container(source) as container:
                video_stream = container.streams.video[0]

                fps = float(video_stream.average_rate) if video_stream.average_rate else 0.0
                duration = float(container.duration / av.time_base) if container.duration else 0.0
                total_frames = video_stream.frames or (int(duration * fps) if fps > 0 else 0)

                return {
                    "duration": duration,
                    "width": video_stream.codec_context.width,
                    "height": video_stream.codec_context.height,
                    "fps": fps,
                    "codec": video_stream.codec_context.name,
                    "total_frames": total_frames,
                    "audio_streams": len(container.streams.audio),
                }
        except Exception:
            logger.exception("Failed to read video info via PyAV")
            return {}

    # ------------------------------------------------------------------
    # Seek-based extraction at explicit timestamps
    # ------------------------------------------------------------------

    @staticmethod
    def extract_frames(
        source: str | bytes,
        timestamps: list[float],
        max_frames: int | None = None,
    ) -> list[tuple[float, np.ndarray]]:
        """Seek to each *timestamp* (seconds) and decode the nearest frame.

        Returns a list of ``(actual_timestamp, rgb_array)`` pairs.
        """
        if not _AV_AVAILABLE:
            logger.error("PyAV not available — cannot extract frames")
            return []

        if not timestamps:
            return []

        effective_ts = sorted(timestamps)
        if max_frames is not None:
            effective_ts = effective_ts[:max_frames]

        results: list[tuple[float, np.ndarray]] = []

        try:
            with _open_container(source) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                time_base = stream.time_base

                for ts_sec in effective_ts:
                    try:
                        pts = int(ts_sec / time_base)
                        container.seek(pts, stream=stream)
                        for frame in container.decode(video=0):
                            actual_ts = (
                                float(frame.pts * time_base) if frame.pts is not None else ts_sec
                            )
                            results.append((actual_ts, _frame_to_rgb_ndarray(frame)))
                            break  # one frame per seek
                    except Exception:
                        logger.debug("Could not decode frame at t=%.3f", ts_sec, exc_info=True)
                        continue
        except Exception:
            logger.exception("Error during PyAV frame extraction")

        return results

    # ------------------------------------------------------------------
    # Uniform distribution
    # ------------------------------------------------------------------

    @classmethod
    def extract_frames_uniform(
        cls,
        source: str | bytes,
        num_frames: int,
    ) -> list[tuple[float, np.ndarray]]:
        """Extract *num_frames* evenly spaced across the video duration."""
        info = cls.get_video_info(source)
        duration = info.get("duration", 0.0)
        if duration <= 0 or num_frames <= 0:
            return []

        if num_frames == 1:
            timestamps = [duration / 2.0]
        else:
            step = duration / (num_frames - 1)
            timestamps = [i * step for i in range(num_frames)]
            # Clamp the last timestamp slightly before the end to avoid EOF seek issues
            timestamps[-1] = min(timestamps[-1], duration - 0.05)

        return cls.extract_frames(source, timestamps, max_frames=num_frames)

    # ------------------------------------------------------------------
    # FPS-based extraction
    # ------------------------------------------------------------------

    @classmethod
    def extract_frames_fps(
        cls,
        source: str | bytes,
        fps: float,
        max_frames: int | None = None,
    ) -> list[tuple[float, np.ndarray]]:
        """Extract frames at the given *fps* rate (e.g. 1.0 = one per second)."""
        if fps <= 0:
            return []

        info = cls.get_video_info(source)
        duration = info.get("duration", 0.0)
        if duration <= 0:
            return []

        interval = 1.0 / fps
        timestamps: list[float] = []
        t = 0.0
        while t < duration:
            timestamps.append(t)
            t += interval

        return cls.extract_frames(source, timestamps, max_frames=max_frames)

    # ------------------------------------------------------------------
    # Keyframe extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_keyframes(
        source: str | bytes,
        max_frames: int | None = None,
    ) -> list[tuple[float, np.ndarray]]:
        """Iterate packets and return decoded keyframes.

        Only I-frames (``packet.is_keyframe``) are decoded, which is
        significantly faster than full decoding.
        """
        if not _AV_AVAILABLE:
            logger.error("PyAV not available — cannot extract keyframes")
            return []

        results: list[tuple[float, np.ndarray]] = []

        try:
            with _open_container(source) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                time_base = stream.time_base

                for packet in container.demux(stream):
                    if packet.dts is None:
                        continue
                    if not packet.is_keyframe:
                        continue

                    for frame in packet.decode():
                        ts = float(frame.pts * time_base) if frame.pts is not None else 0.0
                        results.append((ts, _frame_to_rgb_ndarray(frame)))

                        if max_frames is not None and len(results) >= max_frames:
                            break

                    if max_frames is not None and len(results) >= max_frames:
                        break
        except Exception:
            logger.exception("Error during PyAV keyframe extraction")

        return results

    # ------------------------------------------------------------------
    # Basic scene detection (histogram diff fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def detect_scenes_basic(
        source: str | bytes,
        threshold: float = 0.3,
    ) -> list[float]:
        """Detect scene changes by comparing consecutive frame histograms.

        This is a lightweight fallback — PySceneDetect should be preferred
        for production-grade detection.  Frames are decoded at ~1 fps to
        keep CPU usage reasonable.

        Returns timestamps (seconds) where a scene change was detected.
        """
        if not _AV_AVAILABLE:
            logger.error("PyAV not available — cannot detect scenes")
            return []

        scene_timestamps: list[float] = []

        try:
            with _open_container(source) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                time_base = stream.time_base
                fps = float(stream.average_rate) if stream.average_rate else 25.0

                # Decode every Nth frame (~1 fps)
                decode_interval = max(int(fps), 1)
                prev_hist: np.ndarray | None = None
                frame_index = 0

                for frame in container.decode(video=0):
                    if frame_index % decode_interval != 0:
                        frame_index += 1
                        continue

                    rgb = _frame_to_rgb_ndarray(frame)
                    # Compute normalised grayscale histogram (256 bins)
                    gray = np.mean(rgb, axis=2).astype(np.uint8)
                    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
                    hist = hist.astype(np.float64)
                    hist_sum = hist.sum()
                    if hist_sum > 0:
                        hist /= hist_sum

                    if prev_hist is not None:
                        diff = np.sum(np.abs(hist - prev_hist))
                        if diff > threshold:
                            ts = float(frame.pts * time_base) if frame.pts is not None else 0.0
                            scene_timestamps.append(ts)

                    prev_hist = hist
                    frame_index += 1
        except Exception:
            logger.exception("Error during PyAV basic scene detection")

        return scene_timestamps
