"""
Highlight Detection Service
============================

Business logic for identifying highlight moments in videos suitable for
clips or social media.  Includes multiple detection strategies:

1. **Frame highlights** – frames with rich descriptions distributed across video
2. **Scene highlights** – scenes with visual variety distributed across video
3. **Entity highlights** – frames with multiple entities (key moments)
4. **Fallback highlights** – evenly spaced representative samples

The service is consumed by ``agent/tools/highlight_tools.py`` which
remains a thin wrapper exposing LangGraph ``@tool`` functions.
"""

import logging
from typing import Any

from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


class HighlightDetectionService:
    """Detect and rank highlight moments from a video knowledge graph.

    Parameters
    ----------
    kg:
        A ``KnowledgeGraphService`` instance used for Neo4j queries.
    """

    def __init__(self, kg: Any) -> None:
        self._kg = kg

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def detect_highlights(
        self,
        media_id: str,
        criteria: str = "all",
        max_clips: int = 5,
        min_duration: float = 10.0,
        max_duration: float = 60.0,
    ) -> dict[str, Any]:
        """Run all highlight strategies and return a merged, sorted result.

        Returns a dict compatible with the ``find_highlights`` tool response.
        """
        video_duration = self._get_video_duration(media_id)
        used_ranges: list[tuple[float, float]] = []
        highlights: list[dict[str, Any]] = []

        num_segments = max(max_clips * 2, 10)
        segment_duration = video_duration / num_segments if video_duration > 0 else 300

        # Strategy 1: Frames with rich descriptions
        highlights.extend(
            self.find_frame_highlights(
                media_id, segment_duration, max_clips, min_duration, max_duration, used_ranges
            )
        )

        # Strategy 2: Scenes with visual variety
        if len(highlights) < max_clips:
            highlights.extend(
                self.find_scene_highlights(
                    media_id,
                    segment_duration,
                    max_clips - len(highlights),
                    min_duration,
                    max_duration,
                    used_ranges,
                )
            )

        # Strategy 3: Frames with multiple entities
        if len(highlights) < max_clips:
            highlights.extend(
                self.find_entity_highlights(
                    media_id, max_clips - len(highlights), min_duration, used_ranges
                )
            )

        # Strategy 4: Fallback – evenly spaced key moments
        if len(highlights) < 3:
            highlights.extend(
                self.find_fallback_highlights(
                    media_id,
                    video_duration,
                    max_clips - len(highlights),
                    min_duration,
                    used_ranges,
                )
            )

        highlights.sort(key=lambda h: h["start_time"])

        return self.format_result(criteria, highlights)

    # ------------------------------------------------------------------ #
    # Strategy 1 – Frame highlights
    # ------------------------------------------------------------------ #

    def find_frame_highlights(
        self,
        media_id: str,
        segment_duration: float,
        max_clips: int,
        min_duration: float,
        max_duration: float,
        used_ranges: list[tuple[float, float]],
    ) -> list[dict[str, Any]]:
        """Find frames with rich descriptions distributed across the video.

        Divides the video into segments and picks the best frame from each.
        Updates *used_ranges* in place to prevent overlapping clips.
        """
        highlights: list[dict[str, Any]] = []

        with self._kg.get_session() as session:
            result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $media_id AND f.description IS NOT NULL
                  AND size(f.description) > 80
                RETURN f.timestamp as timestamp, f.description as description,
                       size(f.description) as desc_length
                ORDER BY size(f.description) DESC
                LIMIT 100
                """,
                media_id=media_id,
            )
            candidate_frames = list(result)

        # Best (longest description) per time segment
        segment_best: dict[int, Any] = {}
        for frame in candidate_frames:
            ts = frame.get("timestamp", 0)
            segment_idx = int(ts / segment_duration) if segment_duration > 0 else 0
            if segment_idx not in segment_best or frame.get("desc_length", 0) > segment_best[
                segment_idx
            ].get("desc_length", 0):
                segment_best[segment_idx] = frame

        sorted_segments = sorted(
            segment_best.items(), key=lambda x: x[1].get("desc_length", 0), reverse=True
        )

        video_duration = 0.0
        if candidate_frames:
            video_duration = self._get_video_duration(media_id)

        for _segment_idx, frame in sorted_segments:
            if len(highlights) >= max_clips:
                break

            ts = frame.get("timestamp", 0)
            half_duration = min_duration / 2
            start = max(0, ts - half_duration)
            end = min(
                video_duration if video_duration > 0 else ts + half_duration, ts + half_duration
            )
            if end - start < min_duration:
                end = start + min_duration

            if time_range_overlaps(start, end, used_ranges):
                continue

            desc = frame.get("description", "") or ""
            highlights.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start),
                    "end_formatted": format_timestamp(end),
                    "duration": round(end - start, 1),
                    "title": "Content Highlight",
                    "description": desc[:200],
                    "highlight_reason": "Rich visual content (distributed)",
                    "suggested_for": ["social_clip", "preview"],
                }
            )
            used_ranges.append((start, end))

        return highlights

    # ------------------------------------------------------------------ #
    # Strategy 2 – Scene highlights
    # ------------------------------------------------------------------ #

    def find_scene_highlights(
        self,
        media_id: str,
        segment_duration: float,
        max_clips: int,
        min_duration: float,
        max_duration: float,
        used_ranges: list[tuple[float, float]],
    ) -> list[dict[str, Any]]:
        """Find scenes with visual variety distributed across the video.

        Updates *used_ranges* in place.
        """
        highlights: list[dict[str, Any]] = []

        with self._kg.get_session() as session:
            result = session.run(
                """
                MATCH (s:Scene)
                WHERE s.video_id = $media_id
                WITH s, (s.start_time / $segment_size) as segment
                WITH segment, collect(s) as scenes
                UNWIND scenes[0..1] as scene
                RETURN scene.start_time as start, scene.end_time as end
                ORDER BY segment
                """,
                media_id=media_id,
                segment_size=segment_duration * 2,
            )
            distributed_scenes = list(result)

        for scene in distributed_scenes:
            if len(highlights) >= max_clips:
                break

            start = scene.get("start", 0)
            end = scene.get("end", 0)
            duration = end - start if end else min_duration

            if duration < min_duration or duration > max_duration:
                continue
            if time_range_overlaps(start, end, used_ranges):
                continue

            scene_desc = self._get_scene_description(media_id, start, end)

            highlights.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start),
                    "end_formatted": format_timestamp(end),
                    "duration": round(duration, 1),
                    "title": "Visual Highlight",
                    "description": (
                        scene_desc[:200]
                        if scene_desc
                        else f"Scene from {format_timestamp(start)} to {format_timestamp(end)}"
                    ),
                    "highlight_reason": "Key visual moment",
                    "suggested_for": ["social_clip", "preview"],
                }
            )
            used_ranges.append((start, end))

        return highlights

    # ------------------------------------------------------------------ #
    # Strategy 3 – Entity highlights
    # ------------------------------------------------------------------ #

    def find_entity_highlights(
        self,
        media_id: str,
        max_clips: int,
        min_duration: float,
        used_ranges: list[tuple[float, float]],
    ) -> list[dict[str, Any]]:
        """Find frames with multiple entities (key moments).

        Updates *used_ranges* in place.
        """
        highlights: list[dict[str, Any]] = []

        with self._kg.get_session() as session:
            result = session.run(
                """
                MATCH (e:Entity)-[:APPEARS_IN]->(f:Frame)
                WHERE f.video_id = $media_id
                WITH f, count(e) as entity_count
                WHERE entity_count > 2
                RETURN f.timestamp as timestamp, f.description as description, entity_count
                ORDER BY entity_count DESC
                LIMIT 20
                """,
                media_id=media_id,
            )
            entity_rich_frames = list(result)

        for frame in entity_rich_frames:
            if len(highlights) >= max_clips:
                break

            ts = frame.get("timestamp", 0)
            start = max(0, ts - min_duration / 2)
            end = ts + min_duration / 2

            if time_range_overlaps(start, end, used_ranges):
                continue

            desc = frame.get("description", "") or ""
            highlights.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start),
                    "end_formatted": format_timestamp(end),
                    "duration": round(end - start, 1),
                    "title": "Key Moment",
                    "description": desc[:200],
                    "highlight_reason": (
                        f"Multiple key entities ({frame.get('entity_count', 0)} detected)"
                    ),
                    "suggested_for": ["social_clip", "highlight_reel"],
                }
            )
            used_ranges.append((start, end))

        return highlights

    # ------------------------------------------------------------------ #
    # Strategy 4 – Fallback highlights
    # ------------------------------------------------------------------ #

    def find_fallback_highlights(
        self,
        media_id: str,
        video_duration: float,
        max_clips: int,
        min_duration: float,
        used_ranges: list[tuple[float, float]],
    ) -> list[dict[str, Any]]:
        """Evenly spaced key moments as a fallback strategy.

        Updates *used_ranges* in place.
        """
        highlights: list[dict[str, Any]] = []

        if video_duration <= 0:
            video_duration = self._get_video_duration(media_id)

        if video_duration <= 0:
            return highlights

        sample_points = [
            video_duration * 0.1,
            video_duration * 0.5,
            video_duration * 0.85,
        ]

        for ts in sample_points:
            if len(highlights) >= max_clips:
                break

            start = max(0, ts - min_duration / 2)
            end = min(video_duration, ts + min_duration / 2)

            if time_range_overlaps(start, end, used_ranges):
                continue

            highlights.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start),
                    "end_formatted": format_timestamp(end),
                    "duration": round(end - start, 1),
                    "title": f"Sample at {int(ts / video_duration * 100)}%",
                    "description": (
                        f"Key moment from {format_timestamp(start)} to {format_timestamp(end)}"
                    ),
                    "highlight_reason": "Representative sample",
                    "suggested_for": ["preview"],
                }
            )
            used_ranges.append((start, end))

        return highlights

    # ------------------------------------------------------------------ #
    # Result formatting
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_result(
        criteria: str,
        highlights: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the final response dict for the highlight tool."""
        return {
            "criteria": criteria,
            "total_highlights": len(highlights),
            "highlights": highlights,
            "exportable": True,
            "message": f"Found {len(highlights)} potential highlight clips for this video.",
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_video_duration(self, media_id: str) -> float:
        """Resolve the video duration from the Video node or Scene nodes."""
        with self._kg.get_session() as session:
            result = session.run(
                """
                MATCH (v:Video)
                WHERE v.id = $media_id OR v.video_id = $media_id
                RETURN v.duration as duration
                LIMIT 1
                """,
                media_id=media_id,
            )
            video = result.single()
            duration = video.get("duration", 0) if video else 0

        if not duration:
            with self._kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (s:Scene)
                    WHERE s.video_id = $media_id
                    RETURN max(s.end_time) as max_end
                    """,
                    media_id=media_id,
                )
                rec = result.single()
                duration = rec.get("max_end", 0) if rec else 0

        return float(duration)

    def _get_scene_description(self, media_id: str, start: float, end: float) -> str:
        """Get the best frame description within a scene time range."""
        with self._kg.get_session() as session:
            frame_result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $media_id
                  AND f.timestamp >= $start AND f.timestamp <= $end
                  AND f.description IS NOT NULL
                RETURN f.description as description
                ORDER BY size(f.description) DESC
                LIMIT 1
                """,
                media_id=media_id,
                start=start,
                end=end,
            )
            frame_rec = frame_result.single()
            return (frame_rec.get("description", "") or "") if frame_rec else ""


# ====================================================================== #
# Module-level helpers
# ====================================================================== #


def time_range_overlaps(start: float, end: float, used_ranges: list[tuple[float, float]]) -> bool:
    """Check if a time range overlaps with any existing used ranges."""
    return any(start < used_end and end > used_start for used_start, used_end in used_ranges)


# ====================================================================== #
# Singleton accessor
# ====================================================================== #

_highlight_detection_service: HighlightDetectionService | None = None


def get_highlight_detection_service(
    kg: Any | None = None,
) -> HighlightDetectionService:
    """Get the singleton highlight detection service instance.

    If *kg* is not provided the global ``KnowledgeGraphService`` is used.
    """
    global _highlight_detection_service
    if _highlight_detection_service is None:
        if kg is None:
            from services.knowledge_graph import get_knowledge_graph_service

            kg = get_knowledge_graph_service()
        _highlight_detection_service = HighlightDetectionService(kg)
    return _highlight_detection_service
