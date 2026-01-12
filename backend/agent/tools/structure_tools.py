"""
Structure Tools
===============

Tools for exploring video structure - chapters, scenes, summaries.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.knowledge_graph import get_knowledge_graph_service

logger = logging.getLogger(__name__)


class ListChaptersTool(BaseTool):
    """
    List all chapters/sections of a video.
    """

    name = "list_chapters"
    description = (
        "Get the chapter structure of the video - major sections with their time ranges. "
        "Use this when the user asks about the video's structure or what topics are covered."
    )
    parameters = []  # No parameters needed

    async def execute(self, media_id: str | None, **kwargs) -> dict[str, Any]:
        """List video chapters."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "chapters": [],
            }

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            # Query chapters
            query = """
                MATCH (v:Video)-[:CONTAINS]->(c:Chapter)
                WHERE v.video_id = $media_id OR v.id = $media_id
                RETURN c.id as id,
                       c.title as title,
                       c.summary as summary,
                       c.start_time as start_time,
                       c.end_time as end_time,
                       c.chapter_number as chapter_number
                ORDER BY c.start_time
            """

            with graph_service.get_session() as session:
                result = session.run(query, media_id=media_id)
                records = list(result)

            chapters = []
            for record in records:
                start = record.get("start_time", 0)
                end = record.get("end_time", 0)
                duration = end - start if end and start else 0

                chapters.append({
                    "chapter_number": record.get("chapter_number", len(chapters) + 1),
                    "title": record.get("title", f"Chapter {len(chapters) + 1}"),
                    "summary": record.get("summary"),
                    "start_time": start,
                    "end_time": end,
                    "start_formatted": format_timestamp(start) if start else "0:00",
                    "end_formatted": format_timestamp(end) if end else "",
                    "duration_seconds": duration,
                })

            return {
                "total_chapters": len(chapters),
                "chapters": chapters,
            }

        except Exception as e:
            logger.error(f"List chapters error: {e}")
            return {
                "error": f"Failed to list chapters: {str(e)}",
                "chapters": [],
            }


class GetVideoInfoTool(BaseTool):
    """
    Get basic information about the current video.
    """

    name = "get_video_info"
    description = (
        "Get basic information about the video: title, duration, processing status, etc. "
        "Use this when the user asks general questions about the video."
    )
    parameters = []

    async def execute(self, media_id: str | None, **kwargs) -> dict[str, Any]:
        """Get video info."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "info": None,
            }

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            # Query video node
            query = """
                MATCH (v:Video)
                WHERE v.video_id = $media_id OR v.id = $media_id
                OPTIONAL MATCH (v)-[:CONTAINS]->(f:Frame)
                OPTIONAL MATCH (v)-[:CONTAINS]->(a:AudioSegment)
                OPTIONAL MATCH (v)-[:CONTAINS]->(c:Chapter)
                OPTIONAL MATCH (v)-[:CONTAINS]->(s:Scene)
                RETURN v.title as title,
                       v.duration as duration,
                       v.created_at as created_at,
                       v.processed_at as processed_at,
                       v.summary as summary,
                       count(DISTINCT f) as frame_count,
                       count(DISTINCT a) as audio_segment_count,
                       count(DISTINCT c) as chapter_count,
                       count(DISTINCT s) as scene_count
            """

            with graph_service.get_session() as session:
                result = session.run(query, media_id=media_id)
                record = result.single()

            if not record:
                return {
                    "error": "Video not found in knowledge graph",
                    "info": None,
                }

            duration = record.get("duration", 0)

            return {
                "info": {
                    "media_id": media_id,
                    "title": record.get("title", "Untitled Video"),
                    "duration": duration,
                    "duration_formatted": format_timestamp(duration) if duration else "Unknown",
                    "summary": record.get("summary"),
                    "stats": {
                        "frames_analyzed": record.get("frame_count", 0),
                        "audio_segments": record.get("audio_segment_count", 0),
                        "chapters": record.get("chapter_count", 0),
                        "scenes": record.get("scene_count", 0),
                    },
                },
            }

        except Exception as e:
            logger.error(f"Get video info error: {e}")
            return {
                "error": f"Failed to get video info: {str(e)}",
                "info": None,
            }


class GetSummaryTool(BaseTool):
    """
    Get a summary of the video or a specific chapter/time range.
    """

    name = "get_summary"
    description = (
        "Get a summary of the video content. "
        "Can summarize the entire video, a specific chapter, or a time range. "
        "Use this when the user asks for an overview or summary."
    )
    parameters = [
        ToolParameter(
            name="level",
            type="string",
            description="Summary level: 'video' for entire video, 'chapter' for specific chapter, 'range' for time range",
            required=False,
            enum=["video", "chapter", "range"],
            default="video",
        ),
        ToolParameter(
            name="chapter_number",
            type="integer",
            description="Chapter number to summarize (required if level='chapter')",
            required=False,
        ),
        ToolParameter(
            name="start_time",
            type="number",
            description="Start time in seconds (required if level='range')",
            required=False,
        ),
        ToolParameter(
            name="end_time",
            type="number",
            description="End time in seconds (required if level='range')",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        level: str = "video",
        chapter_number: int | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Get summary."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "summary": None,
            }

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            if level == "video":
                # Get video-level summary from Neo4j
                query = """
                    MATCH (v:Video)
                    WHERE v.video_id = $media_id OR v.id = $media_id
                    RETURN v.summary as summary,
                           v.title as title,
                           v.duration_seconds as duration,
                           v.topics as topics
                """
                with graph_service.get_session() as session:
                    result = session.run(query, media_id=media_id)
                    record = result.single()

                video_title = record.get("title") if record else None
                video_duration = record.get("duration") if record else None
                video_topics = record.get("topics") if record else None

                if record and record.get("summary"):
                    return {
                        "level": "video",
                        "title": video_title,
                        "summary": record.get("summary"),
                        "duration": format_timestamp(video_duration) if video_duration else None,
                        "topics": video_topics,
                    }

                # Try chapters
                chapters_result = await ListChaptersTool().execute(media_id)
                if chapters_result.get("chapters"):
                    chapter_summaries = [
                        f"**{c['title']}** ({c['start_formatted']}): {c.get('summary', 'No summary')}"
                        for c in chapters_result["chapters"]
                    ]
                    return {
                        "level": "video",
                        "summary": "Video chapters:\n" + "\n".join(chapter_summaries),
                    }

                # Fallback: Build summary from sample frames
                frame_query = """
                    MATCH (f:Frame)
                    WHERE f.video_id = $media_id
                    WITH f ORDER BY f.timestamp
                    WITH collect(f) as all_frames
                    WITH all_frames, size(all_frames) as total
                    UNWIND [0, toInteger(total * 0.25), toInteger(total * 0.5), toInteger(total * 0.75), total - 1] as idx
                    WITH all_frames[idx] as frame, total
                    WHERE frame IS NOT NULL
                    RETURN frame.timestamp as timestamp,
                           frame.description as description,
                           total
                    LIMIT 5
                """
                with graph_service.get_session() as session:
                    result = session.run(frame_query, media_id=media_id)
                    frame_records = list(result)

                if frame_records:
                    total_frames = frame_records[0]["total"] if frame_records else 0
                    frame_summaries = []
                    for fr in frame_records:
                        ts = fr.get("timestamp", 0)
                        desc = fr.get("description", "")
                        # Extract first meaningful part of description
                        if desc:
                            lines = desc.split("\n")
                            summary_line = next((l for l in lines if l.strip() and not l.startswith("#")), desc[:200])
                            frame_summaries.append(f"[{format_timestamp(ts)}] {summary_line[:150]}")
                    
                    return {
                        "level": "video",
                        "title": video_title,
                        "duration": format_timestamp(video_duration) if video_duration else None,
                        "total_frames_analyzed": total_frames,
                        "summary": "Video overview based on key moments:\n\n" + "\n\n".join(frame_summaries),
                        "note": "Full summary not available. Showing sample frames throughout the video.",
                    }

                return {
                    "level": "video",
                    "title": video_title,
                    "summary": "No summary or frame data available for this video.",
                }

            elif level == "chapter":
                if chapter_number is None:
                    return {"error": "chapter_number is required for chapter summary"}

                query = """
                    MATCH (v:Video)-[:HAS_CHAPTER]->(c:Chapter)
                    WHERE (v.video_id = $media_id OR v.id = $media_id)
                      AND c.chapter_number = $chapter_number
                    RETURN c.title as title,
                           c.summary as summary,
                           c.start_time as start_time,
                           c.end_time as end_time
                """
                with graph_service.get_session() as session:
                    result = session.run(query, media_id=media_id, chapter_number=chapter_number)
                    record = result.single()

                if record:
                    return {
                        "level": "chapter",
                        "chapter_number": chapter_number,
                        "title": record.get("title"),
                        "time_range": f"{format_timestamp(record.get('start_time', 0))} - {format_timestamp(record.get('end_time', 0))}",
                        "summary": record.get("summary") or "No summary available for this chapter.",
                    }
                return {"error": f"Chapter {chapter_number} not found"}

            elif level == "range":
                if start_time is None or end_time is None:
                    return {"error": "start_time and end_time are required for range summary"}

                # Get content in time range and summarize
                query = """
                    MATCH (f:Frame)
                    WHERE f.video_id = $media_id
                      AND f.timestamp >= $start_time
                      AND f.timestamp <= $end_time
                    RETURN f.description as description, f.timestamp as timestamp
                    ORDER BY f.timestamp
                    LIMIT 10
                """
                with graph_service.get_session() as session:
                    result = session.run(
                        query,
                        media_id=media_id,
                        start_time=start_time,
                        end_time=end_time,
                    )
                    records = list(result)

                if records:
                    descriptions = [r["description"] for r in records if r["description"]]
                    combined = " | ".join(descriptions[:5])
                    return {
                        "level": "range",
                        "time_range": f"{format_timestamp(start_time)} - {format_timestamp(end_time)}",
                        "content_preview": combined,
                        "frames_in_range": len(records),
                    }
                return {
                    "level": "range",
                    "time_range": f"{format_timestamp(start_time)} - {format_timestamp(end_time)}",
                    "summary": "No content found in this time range.",
                }

            return {"error": f"Unknown summary level: {level}"}

        except Exception as e:
            logger.error(f"Get summary error: {e}")
            return {
                "error": f"Failed to get summary: {str(e)}",
                "summary": None,
            }


# Tool instances
list_chapters = ListChaptersTool()
get_video_info = GetVideoInfoTool()
get_summary = GetSummaryTool()
