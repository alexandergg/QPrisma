"""GPU-accelerated scene detection using TransNetV2.

TransNetV2 is a neural network for shot boundary detection that achieves
state-of-the-art accuracy, especially for complex transitions (dissolves,
wipes, fades) where traditional threshold-based methods (FFmpeg,
PySceneDetect) struggle.

Requirements:
    - ``pip install transnetv2 tensorflow`` (or ``torch``)
    - GPU recommended for real-time performance

Usage::

    from services.gpu_scene_detector import TransNetV2SceneDetector

    detector = TransNetV2SceneDetector()
    if detector.is_available:
        scenes = await detector.detect_scenes("video.mp4")

This is currently a **stub** — the interface is fully defined so
downstream code can type-check and feature-flag against it, but actual
detection raises :class:`NotImplementedError` until the ``transnetv2``
package is stable on PyPI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy dependency check — never crashes on import
# ---------------------------------------------------------------------------

_transnetv2_available = False
try:
    import transnetv2  # noqa: F401

    _transnetv2_available = True
except ImportError:
    pass


def is_transnetv2_available() -> bool:
    """Check if TransNetV2 is installed."""
    return _transnetv2_available


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NeuralSceneInfo:
    """Scene boundary detected by neural network.

    Attributes:
        start_frame: First frame index of the scene.
        end_frame: Last frame index of the scene.
        start_time: Scene start in seconds.
        end_time: Scene end in seconds.
        confidence: Model confidence for this boundary (0.0–1.0).
        transition_type: Detected transition kind — ``"cut"``,
            ``"dissolve"``, ``"fade"``, or ``"wipe"``.
    """

    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    confidence: float  # 0.0-1.0, higher = more confident boundary
    transition_type: str = "cut"  # "cut", "dissolve", "fade", "wipe"


# ---------------------------------------------------------------------------
# TransNetV2SceneDetector
# ---------------------------------------------------------------------------


class TransNetV2SceneDetector:
    """Neural scene detection using TransNetV2.

    Advantages over PySceneDetect:

    * Handles gradual transitions (dissolves, fades)
    * Learned features vs. handcrafted thresholds
    * Confidence scores per boundary

    Disadvantages:

    * Requires GPU for real-time performance
    * Larger memory footprint
    * Additional dependency (``transnetv2``)

    This is currently a **stub** — instantiation and property access work
    without any optional dependency, but :meth:`detect_scenes` and
    :meth:`detect_scene_timestamps` raise :class:`NotImplementedError`.
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold
        self._model: Any = None

    @property
    def is_available(self) -> bool:
        return _transnetv2_available

    async def detect_scenes(
        self,
        video_path: str,
        threshold: float | None = None,
    ) -> list[NeuralSceneInfo]:
        """Detect scene boundaries using TransNetV2.

        Args:
            video_path: Filesystem path to the video file.
            threshold: Override the instance-level confidence threshold.

        Raises:
            RuntimeError: If ``transnetv2`` is not installed.
            NotImplementedError: Always (stub).

        .. note::

            **Stub** — raises :class:`NotImplementedError` with setup
            instructions.  Full implementation requires ``transnetv2``
            and a GPU.
        """
        if not self.is_available:
            raise RuntimeError(
                "TransNetV2 is not installed. " "Install with: pip install transnetv2"
            )
        raise NotImplementedError(
            "TransNetV2SceneDetector is a stub. "
            "Full implementation requires transnetv2 + GPU. "
            "Use SceneDetectService (PySceneDetect) as the CPU alternative."
        )

    async def detect_scene_timestamps(
        self,
        video_path: str,
        threshold: float | None = None,
    ) -> list[float]:
        """Get just the scene boundary timestamps (seconds).

        Convenience wrapper around :meth:`detect_scenes` that returns
        only the ``start_time`` of each detected boundary.
        """
        scenes = await self.detect_scenes(video_path, threshold)
        return [s.start_time for s in scenes]
