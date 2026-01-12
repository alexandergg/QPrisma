"""
Navigation Tools
================

Tools for navigating video content - transcripts, scene descriptions, etc.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.knowledge_graph import get_knowledge_graph_service

logger = logging.getLogger(__name__)


class GetTranscriptTool(BaseTool):
    """
    Get transcript/speech content from a video segment.
    """

    name = "get_transcript"
    description = (
        "Get the transcript (what was said) for a specific time range in the video. "
        "Returns the spoken words with timestamps. "
        "Use this when the user asks what was said at a specific time."
    )
    parameters = [
        ToolParameter(
            name="start_time",
            type="number",
            description="Start time in seconds",
            required=True,
        ),
        ToolParameter(
            name="end_time",
            type="number",
            description="End time in seconds (optional, defaults to start_time + 60)",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        start_time: float,
        end_time: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Get transcript for time range."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "segments": [],
            }

        if end_time is None:
            end_time = start_time + 60

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            # Query audio segments via HAS_TRANSCRIPT relationship
            # AudioSegments use start_time/end_time, not timestamp
            query = """
                MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND a.start_time <= $end_time
                  AND a.end_time >= $start_time
                RETURN a.start_time as start_time,
                       a.end_time as end_time_seg,
                       a.text as text,
                       a.speaker_label as speaker,
                       (a.end_time - a.start_time) as duration
                ORDER BY a.start_time
            """

            with graph_service.get_session() as session:
                result = session.run(
                    query,
                    media_id=media_id,
                    start_time=start_time,
                    end_time=end_time,
                )
                records = list(result)

            # Fallback: try direct property match if no HAS_TRANSCRIPT relationship
            if not records:
                query_direct = """
                    MATCH (a:AudioSegment)
                    WHERE a.video_id = $media_id
                      AND a.start_time <= $end_time
                      AND a.end_time >= $start_time
                    RETURN a.start_time as start_time,
                           a.end_time as end_time_seg,
                           a.text as text,
                           a.speaker_label as speaker,
                           (a.end_time - a.start_time) as duration
                    ORDER BY a.start_time
                """
                with graph_service.get_session() as session:
                    result = session.run(
                        query_direct,
                        media_id=media_id,
                        start_time=start_time,
                        end_time=end_time,
                    )
                    records = list(result)

            segments = []
            for record in records:
                ts = record.get("start_time") or 0
                segments.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts) if ts else "N/A",
                    "text": record["text"],
                    "speaker": record.get("speaker"),
                    "duration": record.get("duration"),
                    "end_time": record.get("end_time_seg"),
                })

            # Combine into continuous text
            full_transcript = " ".join([s["text"] for s in segments if s["text"]])

            return {
                "time_range": {
                    "start": start_time,
                    "end": end_time,
                    "start_formatted": format_timestamp(start_time),
                    "end_formatted": format_timestamp(end_time),
                },
                "segments": segments,
                "full_transcript": full_transcript,
                "total_segments": len(segments),
            }

        except Exception as e:
            logger.error(f"Get transcript error: {e}")
            return {
                "error": f"Failed to get transcript: {str(e)}",
                "segments": [],
            }


class DescribeSceneTool(BaseTool):
    """
    Get detailed visual description of a scene at a specific timestamp.
    """

    name = "describe_scene"
    description = (
        "Get a detailed visual description of what's happening at a specific timestamp. "
        "Returns scene descriptions, detected objects, and visual analysis. "
        "Use this when the user asks what's happening at a specific time."
    )
    parameters = [
        ToolParameter(
            name="timestamp",
            type="number",
            description="Timestamp in seconds to describe",
            required=True,
        ),
        ToolParameter(
            name="context_seconds",
            type="number",
            description="How many seconds of context around the timestamp (default: 5)",
            required=False,
            default=5,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        timestamp: float,
        context_seconds: float = 5,
        **kwargs,
    ) -> dict[str, Any]:
        """Describe scene at timestamp."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "description": None,
            }

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            # Get frames around the timestamp
            query = """
                MATCH (v:Video)-[:CONTAINS]->(f:Frame)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND f.timestamp >= $start_time
                  AND f.timestamp <= $end_time
                RETURN f.timestamp as timestamp,
                       f.description as description,
                       f.detected_objects as detected_objects,
                       f.scene_type as scene_type
                ORDER BY abs(f.timestamp - $target_time)
                LIMIT 5
            """

            start_time = max(0, timestamp - context_seconds)
            end_time = timestamp + context_seconds

            with graph_service.get_session() as session:
                result = session.run(
                    query,
                    media_id=media_id,
                    start_time=start_time,
                    end_time=end_time,
                    target_time=timestamp,
                )
                records = list(result)

            if not records:
                # Try to get the nearest frame
                query_nearest = """
                    MATCH (v:Video)-[:CONTAINS]->(f:Frame)
                    WHERE (v.video_id = $media_id OR v.id = $media_id)
                    RETURN f.timestamp as timestamp,
                           f.description as description,
                           f.detected_objects as detected_objects,
                           f.scene_type as scene_type
                    ORDER BY abs(f.timestamp - $target_time)
                    LIMIT 1
                """
                with graph_service.get_session() as session:
                    result = session.run(query_nearest, media_id=media_id, target_time=timestamp)
                    records = list(result)

            frames = []
            all_objects = set()

            for record in records:
                frames.append({
                    "timestamp": record["timestamp"],
                    "timestamp_formatted": format_timestamp(record["timestamp"]),
                    "description": record["description"],
                    "scene_type": record.get("scene_type"),
                })
                if record.get("detected_objects"):
                    for obj in record["detected_objects"]:
                        all_objects.add(obj)

            # Get the main description (closest to requested timestamp)
            main_description = frames[0]["description"] if frames else "No visual data available for this timestamp."

            # Check for related audio using HAS_TRANSCRIPT relationship
            audio_query = """
                MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND a.start_time <= $end_time
                  AND a.end_time >= $start_time
                RETURN a.text as text
                ORDER BY a.start_time
                LIMIT 5
            """
            
            with graph_service.get_session() as session:
                audio_result = session.run(
                    audio_query,
                    media_id=media_id,
                    start_time=start_time,
                    end_time=end_time,
                )
                audio_records = list(audio_result)

            audio_context = " ".join([r["text"] for r in audio_records if r["text"]])

            return {
                "timestamp": timestamp,
                "timestamp_formatted": format_timestamp(timestamp),
                "main_description": main_description,
                "detected_objects": list(all_objects),
                "frames_analyzed": len(frames),
                "audio_context": audio_context or None,
                "context_range": {
                    "start_formatted": format_timestamp(start_time),
                    "end_formatted": format_timestamp(end_time),
                },
            }

        except Exception as e:
            logger.error(f"Describe scene error: {e}")
            return {
                "error": f"Failed to describe scene: {str(e)}",
                "description": None,
            }


# Tool instances
get_transcript = GetTranscriptTool()
describe_scene = DescribeSceneTool()
