"""
Timestamp Calculator

Calculates frame extraction timestamps for various extraction methods
(FPS, INTERVAL, UNIFORM, KEYFRAMES, SCENE_DETECT, ADAPTIVE, HYBRID).
"""

import logging
from collections.abc import Callable
from typing import Any

from models.ffmpeg_config import FrameExtractionConfig, FrameExtractionMethod

logger = logging.getLogger(__name__)


class TimestampCalculator:
    """Calculate frame extraction timestamps for various methods."""

    def calculate_frame_timestamps(
        self,
        video_info: dict[str, Any],
        extraction: FrameExtractionConfig,
        scene_detector: Callable[[str, float, int], list[float]] | None = None,
    ) -> list[float]:
        """
        Calculate timestamps of frames to extract.

        Args:
            video_info: Video information dictionary (must contain ``duration``
                and optionally ``path`` for hybrid/adaptive methods).
            extraction: Frame extraction configuration.
            scene_detector: Optional callable ``(video_path, threshold, max_scenes) -> timestamps``
                used by HYBRID and ADAPTIVE methods for scene detection.

        Returns:
            List of timestamps in seconds.
        """
        duration = video_info["duration"]

        # Apply start/end time
        start = extraction.start_time or 0
        end = min(extraction.end_time or duration, duration)  # Do not exceed actual duration
        effective_duration = end - start

        # Validate that there is a valid duration
        if effective_duration <= 0:
            return []

        timestamps: list[float] = []

        if extraction.method == FrameExtractionMethod.FPS:
            # Extract at specific FPS
            interval = 1.0 / extraction.fps
            t = start
            while t < end and len(timestamps) < extraction.max_frames:
                timestamps.append(t)
                t += interval

            # Ensure we do not exceed the duration
            timestamps = [t for t in timestamps if t < duration]

        elif extraction.method == FrameExtractionMethod.INTERVAL:
            # Extract every N seconds
            t = start
            while t < end and len(timestamps) < extraction.max_frames:
                timestamps.append(t)
                t += extraction.interval_seconds

            # Ensure we do not exceed the duration
            timestamps = [t for t in timestamps if t < duration]

        elif extraction.method == FrameExtractionMethod.UNIFORM:
            # Distribute uniformly
            num = min(extraction.num_frames, extraction.max_frames)
            if num > 1:
                step = effective_duration / (num - 1)
                timestamps = [start + i * step for i in range(num)]
            else:
                timestamps = [start + effective_duration / 2]

            # Ensure we do not exceed the duration (adjust last frame if necessary)
            timestamps = [min(t, duration - 0.1) for t in timestamps]

        elif extraction.method == FrameExtractionMethod.KEYFRAMES:
            # This requires prior analysis - handled differently
            return []  # Will be processed with select filter

        elif extraction.method == FrameExtractionMethod.SCENE_DETECT:
            # Also requires prior analysis
            return []  # Will be processed with scene detection

        elif extraction.method == FrameExtractionMethod.ADAPTIVE:
            # Calculate optimal configuration based on duration
            from models.ffmpeg_config import get_adaptive_config

            adaptive_config = get_adaptive_config(duration)
            # Use the calculated method (can be INTERVAL or HYBRID)
            if adaptive_config.method == FrameExtractionMethod.HYBRID:
                # Delegate to HYBRID
                return self.calculate_hybrid_timestamps(
                    video_info,
                    extraction,
                    adaptive_config.scene_threshold or 0.3,
                    adaptive_config.hybrid_scene_ratio or 0.5,
                    adaptive_config.hybrid_min_gap_seconds or 15.0,
                    adaptive_config.max_frames or 500,
                    scene_detector,
                )
            else:
                # Use INTERVAL with adaptive parameters
                t = start
                interval = adaptive_config.interval_seconds or 5.0
                max_frames = adaptive_config.max_frames or 500
                while t < end and len(timestamps) < max_frames:
                    timestamps.append(t)
                    t += interval

        elif extraction.method == FrameExtractionMethod.HYBRID:
            # Hybrid mode: scene detection + uniform fill
            return self.calculate_hybrid_timestamps(
                video_info,
                extraction,
                extraction.scene_threshold or 0.3,
                extraction.hybrid_scene_ratio or 0.5,
                extraction.hybrid_min_gap_seconds or 15.0,
                extraction.max_frames or 500,
                scene_detector,
            )

        return timestamps[: extraction.max_frames]

    def calculate_hybrid_timestamps(
        self,
        video_info: dict[str, Any],
        extraction: FrameExtractionConfig,
        scene_threshold: float,
        scene_ratio: float,
        min_gap_seconds: float,
        max_frames: int,
        scene_detector: Callable[[str, float, int], list[float]] | None = None,
    ) -> list[float]:
        """
        Calculate timestamps using the hybrid method: scene detection + uniform fill.

        1. Detects scene changes (captures important transitions)
        2. Fills long gaps with uniform frames (avoids missing static content)

        Args:
            video_info: Video information dictionary.
            extraction: Frame extraction configuration (used for start/end time).
            scene_threshold: Scene detection threshold (0-1).
            scene_ratio: Ratio of scene frames vs fill frames (0.6 = 60% scenes).
            min_gap_seconds: Minimum gap before inserting fill frames.
            max_frames: Maximum number of frames to extract.
            scene_detector: Callable ``(video_path, threshold, max_scenes) -> timestamps``.

        Returns:
            Sorted list of timestamps.
        """
        duration = video_info["duration"]
        start = extraction.start_time or 0
        end = min(extraction.end_time or duration, duration)

        # Step 1: Detect scenes
        scene_frames_target = int(max_frames * scene_ratio)
        scene_timestamps: list[float] = []
        if scene_detector is not None:
            scene_timestamps = scene_detector(
                video_info.get("path", ""), scene_threshold, scene_frames_target
            )

        # If scene detection yields nothing, fall back to uniform distribution
        if not scene_timestamps:
            # Uniform distribution as fallback
            num_frames = max_frames
            step = (end - start) / max(num_frames - 1, 1)
            return [start + i * step for i in range(num_frames)]

        # Step 2: Identify gaps and fill them
        fill_frames_target = max_frames - len(scene_timestamps)
        all_timestamps = sorted(scene_timestamps)

        if fill_frames_target > 0 and len(all_timestamps) > 1:
            gaps = []
            for i in range(len(all_timestamps) - 1):
                gap_start = all_timestamps[i]
                gap_end = all_timestamps[i + 1]
                gap_duration = gap_end - gap_start
                if gap_duration > min_gap_seconds:
                    gaps.append((gap_start, gap_end, gap_duration))

            # Distribute fill frames proportionally across gaps
            total_gap_duration = sum(g[2] for g in gaps)
            if total_gap_duration > 0:
                for gap_start, _gap_end, gap_duration in gaps:
                    # Frames to insert in this gap
                    gap_frames = int((gap_duration / total_gap_duration) * fill_frames_target)
                    if gap_frames > 0:
                        step = gap_duration / (gap_frames + 1)
                        for j in range(1, gap_frames + 1):
                            fill_ts = gap_start + j * step
                            if fill_ts not in all_timestamps:
                                all_timestamps.append(fill_ts)

        # Add start and end if not already present
        if start not in all_timestamps and start >= 0:
            all_timestamps.append(start)
        if end - 0.5 not in all_timestamps and end <= duration:
            all_timestamps.append(min(end - 0.1, duration - 0.1))

        # Sort and limit
        all_timestamps = sorted(set(all_timestamps))
        return all_timestamps[:max_frames]
