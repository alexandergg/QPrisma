"""Professional scene detection using PySceneDetect.

Provides accurate scene boundary detection with support for adaptive
(handles gradual transitions, camera motion) and content-based
(fast hard-cut detection) methods.  All public methods are synchronous
and CPU-bound — callers in async contexts should wrap them with
``asyncio.to_thread()``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded flag — set on first import attempt
# ---------------------------------------------------------------------------
_SCENEDETECT_AVAILABLE: bool | None = None


def _check_scenedetect() -> bool:
    """Return *True* if ``scenedetect`` is importable, caching the result."""
    global _SCENEDETECT_AVAILABLE
    if _SCENEDETECT_AVAILABLE is None:
        try:
            import scenedetect  # noqa: F401

            _SCENEDETECT_AVAILABLE = True
        except ImportError:
            logger.warning(
                "PySceneDetect is not installed. "
                "Install with: pip install 'scenedetect[opencv]>=0.6.7'"
            )
            _SCENEDETECT_AVAILABLE = False
    return _SCENEDETECT_AVAILABLE


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SceneInfo:
    """Represents a single detected scene with precise time & frame bounds."""

    start_time: float  # seconds
    end_time: float  # seconds
    start_frame: int
    end_frame: int


# ---------------------------------------------------------------------------
# Threshold mapping helpers
# ---------------------------------------------------------------------------

# FFmpeg scene threshold is 0.0-1.0 (default ~0.3).
# AdaptiveDetector  threshold is typically 2.0-4.0 (default 3.0).
# ContentDetector   threshold is typically 20-35  (default 27.0).

_ADAPTIVE_DEFAULT: float = 3.0
_CONTENT_DEFAULT: float = 27.0


def map_ffmpeg_threshold(
    ffmpeg_threshold: float,
    method: str = "adaptive",
) -> float:
    """Map an FFmpeg-style 0-1 scene threshold to a PySceneDetect value.

    Args:
        ffmpeg_threshold: Value in [0, 1].  Lower → more sensitive.
        method: ``"adaptive"`` or ``"content"``.

    Returns:
        Equivalent PySceneDetect detector threshold.
    """
    clamped = max(0.0, min(1.0, ffmpeg_threshold))
    if method == "content":
        # 0.0 → 15 (very sensitive)  …  1.0 → 40 (very insensitive)
        return 15.0 + clamped * 25.0
    # adaptive: 0.0 → 1.5  …  1.0 → 5.0
    return 1.5 + clamped * 3.5


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SceneDetectService:
    """Scene detection powered by PySceneDetect.

    All public methods are **synchronous** and CPU-bound.  In async code
    wrap calls with ``asyncio.to_thread(service.method, ...)``.
    """

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    def detect_scenes(
        self,
        video_path: str,
        method: str = "adaptive",
        threshold: float | None = None,
    ) -> list[SceneInfo]:
        """Detect scene boundaries in *video_path*.

        Args:
            video_path: Filesystem path to the video file.
            method: ``"adaptive"`` (default) or ``"content"``.
            threshold: Detector-specific threshold.  When *None* the
                library default is used (3.0 for adaptive, 27.0 for
                content).

        Returns:
            Ordered list of :class:`SceneInfo` objects.  An empty list is
            returned when the library is unavailable, the file does not
            exist, or no scene cuts are found.
        """
        if not _check_scenedetect():
            return []

        if not video_path or not os.path.exists(video_path):
            logger.warning("Scene detection skipped: invalid path %r", video_path)
            return []

        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector, ContentDetector

        try:
            video = open_video(video_path)
        except Exception:
            logger.exception("Failed to open video for scene detection: %s", video_path)
            return []

        scene_manager = SceneManager()

        if method == "content":
            detector = ContentDetector(
                threshold=threshold if threshold is not None else _CONTENT_DEFAULT
            )
        else:
            detector = AdaptiveDetector(
                adaptive_threshold=threshold if threshold is not None else _ADAPTIVE_DEFAULT
            )

        scene_manager.add_detector(detector)

        try:
            scene_manager.detect_scenes(video)
        except Exception:
            logger.exception("PySceneDetect analysis failed for %s", video_path)
            return []

        scene_list = scene_manager.get_scene_list()

        if not scene_list:
            logger.info("No scenes detected in %s (method=%s)", video_path, method)
            return []

        scenes: list[SceneInfo] = []
        for start_tc, end_tc in scene_list:
            scenes.append(
                SceneInfo(
                    start_time=start_tc.get_seconds(),
                    end_time=end_tc.get_seconds(),
                    start_frame=start_tc.get_frames(),
                    end_frame=end_tc.get_frames(),
                )
            )

        logger.info(
            "Detected %d scene(s) in %s (method=%s, threshold=%s)",
            len(scenes),
            video_path,
            method,
            threshold,
        )
        return scenes

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def detect_scene_timestamps(
        self,
        video_path: str,
        method: str = "adaptive",
        threshold: float | None = None,
    ) -> list[float]:
        """Return scene-boundary start timestamps (seconds).

        This is a thin wrapper around :meth:`detect_scenes` that returns
        only the ``start_time`` of each detected scene.
        """
        return [s.start_time for s in self.detect_scenes(video_path, method, threshold)]

    def get_scene_frames(
        self,
        video_path: str,
        method: str = "adaptive",
        threshold: float | None = None,
    ) -> list[tuple[float, int]]:
        """Return the mid-point frame of each scene.

        Returns:
            List of ``(timestamp, frame_number)`` tuples representing the
            middle of each scene — useful for extracting a single
            representative frame per scene.
        """
        result: list[tuple[float, int]] = []
        for scene in self.detect_scenes(video_path, method, threshold):
            mid_time = (scene.start_time + scene.end_time) / 2.0
            mid_frame = (scene.start_frame + scene.end_frame) // 2
            result.append((mid_time, mid_frame))
        return result
