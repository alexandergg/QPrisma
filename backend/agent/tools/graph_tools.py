"""
Graph Tools
===========

Tools for navigating the knowledge graph - relationships, timeline, etc.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.knowledge_graph import get_knowledge_graph_service

logger = logging.getLogger(__name__)


class GetRelatedContentTool(BaseTool):
    """
    Find content related to a specific entity or concept.
    """

    name = "get_related_content"
    description = (
        "Explore the knowledge graph to find content related to a topic or entity. "
        "Finds connections between concepts, people, and objects in the video. "
        "Use this to understand how different parts of the video connect."
    )
    parameters = [
        ToolParameter(
            name="topic",
            type="string",
            description="The topic or entity to explore relationships for",
            required=True,
        ),
        ToolParameter(
            name="max_hops",
            type="integer",
            description="How many relationship hops to explore (1-3, default: 2)",
            required=False,
            default=2,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        topic: str,
        max_hops: int = 2,
        **kwargs,
    ) -> dict[str, Any]:
        """Find related content."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "related": [],
            }

        max_hops = min(max(1, max_hops), 3)  # Clamp to 1-3

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            with graph_service.get_session() as session:
                # Neo4j doesn't support variable in path length, so use multiple queries
                result = session.run(
                    """
                    MATCH (v:Video)-[:CONTAINS]->(e:Entity)
                    WHERE (v.video_id = $media_id OR v.id = $media_id)
                      AND (toLower(e.name) CONTAINS toLower($topic))
                    WITH e LIMIT 5
                    OPTIONAL MATCH (e)-[r]-(related)
                    WHERE related:Entity OR related:Frame OR related:Scene
                    RETURN DISTINCT
                        e.name as source_entity,
                        type(r) as relationship,
                        labels(related)[0] as related_type,
                        CASE
                            WHEN related:Entity THEN related.name
                            WHEN related:Frame THEN substring(related.description, 0, 150)
                            WHEN related:Scene THEN substring(related.summary, 0, 150)
                        END as related_content,
                        related.timestamp as timestamp
                    LIMIT 15
                    """,
                    media_id=media_id,
                    topic=topic,
                )
                records = list(result)

            if not records:
                # Try searching in frame descriptions
                result2 = graph_service.get_session().run(
                    """
                    MATCH (v:Video)-[:CONTAINS]->(f:Frame)
                    WHERE (v.video_id = $media_id OR v.id = $media_id)
                      AND toLower(f.description) CONTAINS toLower($topic)
                    RETURN 'Frame' as source_entity,
                           'CONTAINS' as relationship,
                           'Frame' as related_type,
                           substring(f.description, 0, 150) as related_content,
                           f.timestamp as timestamp
                    LIMIT 10
                    """,
                    media_id=media_id,
                    topic=topic,
                )
                records = list(result2)

            related = []
            for record in records:
                ts = record.get("timestamp")
                related.append({
                    "source": record.get("source_entity"),
                    "relationship": record.get("relationship"),
                    "related_type": record.get("related_type"),
                    "content": record.get("related_content"),
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts) if ts else None,
                })

            return {
                "topic": topic,
                "total_connections": len(related),
                "related": related,
            }

        except Exception as e:
            logger.error(f"Get related content error: {e}")
            return {
                "error": f"Failed to explore relationships: {str(e)}",
                "related": [],
            }


class NavigateTimelineTool(BaseTool):
    """
    Navigate to a specific point in the video timeline.
    """

    name = "navigate_timeline"
    description = (
        "Get information about what happens at or around a specific timestamp. "
        "Returns visual content, audio, and any notable events. "
        "Use this when the user asks to go to a specific time."
    )
    parameters = [
        ToolParameter(
            name="timestamp",
            type="number",
            description="Target timestamp in seconds",
            required=True,
        ),
        ToolParameter(
            name="direction",
            type="string",
            description="Direction to navigate: 'at' for exact time, 'before' for previous content, 'after' for next content",
            required=False,
            enum=["at", "before", "after"],
            default="at",
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        timestamp: float,
        direction: str = "at",
        **kwargs,
    ) -> dict[str, Any]:
        """Navigate timeline."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "content": None,
            }

        try:
            graph_service = get_knowledge_graph_service()

            if not graph_service.is_connected:
                graph_service.connect()

            # Build query based on direction
            if direction == "before":
                frame_condition = "f.timestamp < $timestamp"
                order = "DESC"
            elif direction == "after":
                frame_condition = "f.timestamp > $timestamp"
                order = "ASC"
            else:  # at
                frame_condition = "f.timestamp >= $timestamp - 5 AND f.timestamp <= $timestamp + 5"
                order = "ASC"

            query = f"""
                MATCH (v:Video)-[:CONTAINS]->(f:Frame)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND {frame_condition}
                RETURN f.timestamp as timestamp,
                       f.description as description,
                       f.detected_objects as objects
                ORDER BY f.timestamp {order}
                LIMIT 3
            """

            with graph_service.get_session() as session:
                result = session.run(query, media_id=media_id, timestamp=timestamp)
                frame_records = list(result)

            # Get audio around the timestamp
            audio_query = """
                MATCH (v:Video)-[:CONTAINS]->(a:AudioSegment)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND a.timestamp >= $start_time
                  AND a.timestamp <= $end_time
                RETURN a.timestamp as timestamp, a.text as text
                ORDER BY a.timestamp
                LIMIT 3
            """

            with graph_service.get_session() as session:
                audio_result = session.run(
                    audio_query,
                    media_id=media_id,
                    start_time=timestamp - 10,
                    end_time=timestamp + 10,
                )
                audio_records = list(audio_result)

            # Get current chapter
            chapter_query = """
                MATCH (v:Video)-[:CONTAINS]->(c:Chapter)
                WHERE (v.video_id = $media_id OR v.id = $media_id)
                  AND c.start_time <= $timestamp
                  AND c.end_time >= $timestamp
                RETURN c.title as title, c.chapter_number as number
                LIMIT 1
            """

            with graph_service.get_session() as session:
                chapter_result = session.run(chapter_query, media_id=media_id, timestamp=timestamp)
                chapter_record = chapter_result.single()

            # Format response
            frames = []
            for record in frame_records:
                frames.append({
                    "timestamp": record["timestamp"],
                    "timestamp_formatted": format_timestamp(record["timestamp"]),
                    "description": record["description"],
                    "objects": record.get("objects", []),
                })

            audio_segments = []
            for record in audio_records:
                audio_segments.append({
                    "timestamp": record["timestamp"],
                    "timestamp_formatted": format_timestamp(record["timestamp"]),
                    "text": record["text"],
                })

            return {
                "target_timestamp": timestamp,
                "target_formatted": format_timestamp(timestamp),
                "direction": direction,
                "current_chapter": {
                    "number": chapter_record.get("number"),
                    "title": chapter_record.get("title"),
                } if chapter_record else None,
                "visual_content": frames,
                "audio_content": audio_segments,
            }

        except Exception as e:
            logger.error(f"Navigate timeline error: {e}")
            return {
                "error": f"Failed to navigate timeline: {str(e)}",
                "content": None,
            }


# Tool instances
get_related_content = GetRelatedContentTool()
navigate_timeline = NavigateTimelineTool()
