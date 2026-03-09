"""
Highlight Tools
===============

LangGraph tools for identifying highlight moments suitable for clips or social media.
Includes multiple detection strategies: frame analysis, scene variety,
entity density, and fallback sampling.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


# =============================================================================
# Highlight Detection Strategies (private helpers)
# =============================================================================


def _time_range_overlaps(start: float, end: float, used_ranges: list[tuple[float, float]]) -> bool:
    """Check if a time range overlaps with any existing used ranges."""
    return any(start < used_end and end > used_start for used_start, used_end in used_ranges)


def _find_frame_highlights(
    kg,
    media_id: str,
    segment_duration: float,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 1: Find frames with rich descriptions distributed across video.
    Divides video into segments and picks the best frame from each segment.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    # Get candidate frames with rich descriptions
    with kg.get_session() as session:
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

    # Distribute frames across video by picking best from different time segments
    segment_best = {}
    for frame in candidate_frames:
        ts = frame.get("timestamp", 0)
        segment_idx = int(ts / segment_duration) if segment_duration > 0 else 0

        # Keep best (longest description) per segment
        if segment_idx not in segment_best or frame.get("desc_length", 0) > segment_best[
            segment_idx
        ].get("desc_length", 0):
            segment_best[segment_idx] = frame

    # Sort segments by quality and pick top ones, distributed across video
    sorted_segments = sorted(
        segment_best.items(), key=lambda x: x[1].get("desc_length", 0), reverse=True
    )

    # Get video duration from first frame if available
    video_duration = 0
    if candidate_frames:
        with kg.get_session() as session:
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
            video_duration = video.get("duration", 0) if video else 0

    for _segment_idx, frame in sorted_segments:
        if len(highlights) >= max_clips:
            break

        ts = frame.get("timestamp", 0)
        # Create clip around this timestamp
        half_duration = min_duration / 2
        start = max(0, ts - half_duration)
        end = min(video_duration if video_duration > 0 else ts + half_duration, ts + half_duration)

        # Ensure minimum duration
        if end - start < min_duration:
            end = start + min_duration

        if _time_range_overlaps(start, end, used_ranges):
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


def _find_scene_highlights(
    kg,
    media_id: str,
    segment_duration: float,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 2: Find scenes with visual variety distributed across video.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    with kg.get_session() as session:
        # Get scenes from different parts of the video
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
        if _time_range_overlaps(start, end, used_ranges):
            continue

        # Get description from a frame within this scene
        scene_desc = ""
        with kg.get_session() as session:
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
            if frame_rec:
                scene_desc = frame_rec.get("description", "") or ""

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


def _find_entity_highlights(
    kg,
    media_id: str,
    max_clips: int,
    min_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 3: Find frames with multiple entities (key moments).
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    with kg.get_session() as session:
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

        if _time_range_overlaps(start, end, used_ranges):
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
                "highlight_reason": f"Multiple key entities ({frame.get('entity_count', 0)} detected)",
                "suggested_for": ["social_clip", "highlight_reel"],
            }
        )
        used_ranges.append((start, end))

    return highlights


def _find_fallback_highlights(
    kg,
    media_id: str,
    video_duration: float,
    max_clips: int,
    min_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 4: Fallback - evenly spaced key moments from video.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    if video_duration <= 0:
        with kg.get_session() as session:
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
            video_duration = video.get("duration", 0) if video else 0

    if video_duration > 0:
        # Sample evenly from first 3rd, middle, and last 3rd
        sample_points = [
            video_duration * 0.1,  # 10% mark
            video_duration * 0.5,  # Middle
            video_duration * 0.85,  # Near end
        ]

        for ts in sample_points:
            if len(highlights) >= max_clips:
                break

            start = max(0, ts - min_duration / 2)
            end = min(video_duration, ts + min_duration / 2)

            if _time_range_overlaps(start, end, used_ranges):
                continue

            highlights.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start),
                    "end_formatted": format_timestamp(end),
                    "duration": round(end - start, 1),
                    "title": f"Sample at {int(ts/video_duration*100)}%",
                    "description": f"Key moment from {format_timestamp(start)} to {format_timestamp(end)}",
                    "highlight_reason": "Representative sample",
                    "suggested_for": ["preview"],
                }
            )
            used_ranges.append((start, end))

    return highlights


# =============================================================================
# Main Highlight Tool
# =============================================================================


@tool
async def find_highlights(
    criteria: Annotated[
        str, "What makes a moment a highlight: 'engagement', 'action', 'key_topics', 'all'"
    ] = "all",
    max_clips: Annotated[int, "Maximum number of highlight clips to suggest"] = 5,
    min_duration: Annotated[float, "Minimum clip duration in seconds"] = 10.0,
    max_duration: Annotated[float, "Maximum clip duration in seconds"] = 60.0,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Identify highlight moments suitable for clips or social media.
    Returns exportable time ranges with descriptions of why they're highlights.
    """
    if not media_id:
        return {"error": "No video context available.", "highlights": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        highlights = []
        used_ranges = []

        # Get video duration for distributing highlights
        video_duration = 0
        with kg.get_session() as session:
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
            video_duration = video.get("duration", 0) if video else 0

        # If no video node, estimate from max scene end time
        if not video_duration:
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (s:Scene)
                    WHERE s.video_id = $media_id
                    RETURN max(s.end_time) as max_end
                    """,
                    media_id=media_id,
                )
                rec = result.single()
                video_duration = rec.get("max_end", 0) if rec else 0

        # Calculate segment duration for strategies
        num_segments = max(max_clips * 2, 10)
        segment_duration = video_duration / num_segments if video_duration > 0 else 300

        # Strategy 1: Frames with rich descriptions distributed across video
        frame_highlights = _find_frame_highlights(
            kg, media_id, segment_duration, max_clips, min_duration, max_duration, used_ranges
        )
        highlights.extend(frame_highlights)

        # Strategy 2: Scenes with visual variety
        if len(highlights) < max_clips:
            scene_highlights = _find_scene_highlights(
                kg,
                media_id,
                segment_duration,
                max_clips - len(highlights),
                min_duration,
                max_duration,
                used_ranges,
            )
            highlights.extend(scene_highlights)

        # Strategy 3: Frames with multiple entities
        if len(highlights) < max_clips:
            entity_highlights = _find_entity_highlights(
                kg, media_id, max_clips - len(highlights), min_duration, used_ranges
            )
            highlights.extend(entity_highlights)

        # Strategy 4: Fallback - evenly spaced key moments
        if len(highlights) < 3:
            fallback_highlights = _find_fallback_highlights(
                kg, media_id, video_duration, max_clips - len(highlights), min_duration, used_ranges
            )
            highlights.extend(fallback_highlights)

        # Sort by start time
        highlights.sort(key=lambda x: x["start_time"])

        return {
            "criteria": criteria,
            "total_highlights": len(highlights),
            "highlights": highlights,
            "exportable": True,
            "message": f"Found {len(highlights)} potential highlight clips for this video.",
        }

    except Exception as e:
        return {"error": f"Failed to find highlights: {str(e)}", "highlights": []}
