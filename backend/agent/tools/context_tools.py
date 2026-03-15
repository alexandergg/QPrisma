"""
Context Tools
=============

LangGraph tools for retrieving video context, chapters, summaries, and metadata.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


@tool
async def list_chapters(
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get the chapter structure and overview of the video.
    """
    if not media_id:
        return {"error": "No video context available.", "chapters": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "chapters": []}

        with kg.get_session() as session:
            # Get scenes as chapters using video_id property
            result = session.run(
                """
                MATCH (s:Scene)
                WHERE s.video_id = $media_id
                RETURN s.id as id, s.start_time as start_time, s.end_time as end_time,
                       s.description as description, s.scene_type as scene_type
                ORDER BY s.start_time
                """,
                media_id=media_id,
            )
            scenes = list(result)

        if not scenes:
            # Try to get video topics as alternative
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (v:Video)
                    WHERE v.video_id = $media_id OR v.id = $media_id
                    RETURN v.topics as topics,
                           v.summary as summary
                    """,
                    media_id=media_id,
                )
                record = result.single()
                if record and record.get("topics"):
                    return {
                        "message": "No chapters found, but here are the main topics covered:",
                        "topics": record.get("topics", []),
                        "summary": record.get("summary", ""),
                        "chapters": [],
                    }
            return {"message": "No chapters found for this video.", "chapters": []}

        return {
            "total_chapters": len(scenes),
            "chapters": [
                {
                    "number": i + 1,
                    "title": scene.get("scene_type") or f"Scene {i + 1}",
                    "start_time": scene.get("start_time", 0),
                    "start_formatted": format_timestamp(scene.get("start_time", 0)),
                    "end_time": scene.get("end_time", 0),
                    "end_formatted": format_timestamp(scene.get("end_time", 0)),
                    "summary": scene.get("description", ""),
                }
                for i, scene in enumerate(scenes)
            ],
        }

    except Exception as e:
        return {"error": f"Failed to get chapters: {str(e)}", "chapters": []}


@tool
async def get_video_info(
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get basic information about the current video (title, duration, etc.).
    """
    if not media_id:
        return {"error": "No video context available."}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        media = db.get_media(media_id)

        if not media:
            return {"error": "Video not found."}

        metadata = media.video_metadata or {}

        return {
            "media_id": media_id,
            "title": media.original_filename or media.blob_name,
            "duration": metadata.get("duration", 0),
            "duration_formatted": format_timestamp(metadata.get("duration", 0)),
            "resolution": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
            "fps": metadata.get("fps", 0),
            "status": media.processing_status,
        }

    except Exception as e:
        return {"error": f"Failed to get video info: {str(e)}"}


@tool
async def get_summary(
    level: Annotated[str, "Summary level: 'brief', 'detailed', or 'comprehensive'"] = "brief",
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get a summary of the video content at different levels of detail.
    """
    if not media_id:
        return {"error": "No video context available.", "summary": ""}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "summary": ""}

        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (v:Video)
                WHERE v.video_id = $media_id OR v.id = $media_id
                RETURN v.summary as summary,
                       v.title as title, v.topics as topics,
                       v.duration_seconds as duration
                """,
                media_id=media_id,
            )
            record = result.single()

        if not record or not record.get("summary"):
            return {
                "level": level,
                "summary": "No summary available for this video.",
                "title": record.get("title") if record else "Unknown",
            }

        summary = record.get("summary", "")
        topics = record.get("topics", [])
        title = record.get("title", "")
        duration = record.get("duration", 0)

        return {
            "level": level,
            "summary": summary,
            "title": title,
            "topics": topics or [],
            "duration_formatted": format_timestamp(duration) if duration else None,
        }

    except Exception as e:
        return {"error": f"Failed to get summary: {str(e)}", "summary": ""}


@tool
async def get_scene_context(
    timestamp: Annotated[float, "Center timestamp in seconds"],
    window_seconds: Annotated[float, "Context window size (seconds before and after)"] = 30.0,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get comprehensive context around a specific moment in the video.
    Returns frames, audio, and scene information within the time window.
    Use this for understanding what happened before, during, and after a moment.
    Uses temporal chain traversal when available for seamless cross-scene context.
    """
    if not media_id:
        return {"error": "No video context available.", "context": {}}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "context": {}}

        start_time = max(0, timestamp - window_seconds)
        end_time = timestamp + window_seconds

        # Get frames — try chain walk from nearest frame, fallback to property query
        frames = []
        with kg.get_session() as session:
            # Find the anchor frame closest to center timestamp
            anchor_result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $media_id
                  AND f.timestamp >= $start_time AND f.timestamp <= $end_time
                RETURN f.id AS id, f.timestamp AS ts
                ORDER BY abs(f.timestamp - $timestamp)
                LIMIT 1
                """,
                media_id=media_id,
                start_time=start_time,
                end_time=end_time,
                timestamp=timestamp,
            )
            anchor = anchor_result.single()

            if anchor:
                max_hops = max(int(window_seconds / 2), 10)
                frame_chain_query = """
                    MATCH (anchor:Frame {id: $anchor_id})
                    OPTIONAL MATCH bwd = (prev:Frame)-[:NEXT_FRAME*1..{hops}]->(anchor)
                    WHERE prev.timestamp >= $start_time
                    WITH anchor, collect(DISTINCT prev) AS before_nodes
                    OPTIONAL MATCH fwd = (anchor)-[:NEXT_FRAME*1..{hops}]->(nxt:Frame)
                    WHERE nxt.timestamp <= $end_time
                    WITH anchor, before_nodes, collect(DISTINCT nxt) AS after_nodes
                    WITH before_nodes + [anchor] + after_nodes AS all_nodes
                    UNWIND all_nodes AS f
                    WITH DISTINCT f
                    RETURN f.timestamp AS timestamp, f.description AS description
                    ORDER BY f.timestamp
                    """
                frame_chain_query = frame_chain_query.replace("{hops}", str(max_hops))
                chain_result = session.run(
                    frame_chain_query,
                    anchor_id=anchor["id"],
                    start_time=start_time,
                    end_time=end_time,
                )
                frames = list(chain_result)

        # Fallback to property-based query
        if not frames:
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (f:Frame)
                    WHERE f.video_id = $media_id
                      AND f.timestamp >= $start_time
                      AND f.timestamp <= $end_time
                    RETURN f.timestamp as timestamp, f.description as description
                    ORDER BY f.timestamp
                    """,
                    media_id=media_id,
                    start_time=start_time,
                    end_time=end_time,
                )
                frames = list(result)

        # Get audio segments — try chain walk, fallback to property query
        audio_segments = []
        with kg.get_session() as session:
            anchor_result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $media_id
                  AND a.start_time >= $start_time AND a.start_time <= $end_time
                RETURN a.id AS id
                ORDER BY abs(a.start_time - $timestamp)
                LIMIT 1
                """,
                media_id=media_id,
                start_time=start_time,
                end_time=end_time,
                timestamp=timestamp,
            )
            anchor = anchor_result.single()

            if anchor:
                max_hops = max(int(window_seconds), 20)
                audio_chain_query = """
                    MATCH (anchor:AudioSegment {id: $anchor_id})
                    OPTIONAL MATCH (prev:AudioSegment)-[:NEXT_SEGMENT*1..{hops}]->(anchor)
                    WHERE prev.start_time >= $start_time
                    WITH anchor, collect(DISTINCT prev) AS before_nodes
                    OPTIONAL MATCH (anchor)-[:NEXT_SEGMENT*1..{hops}]->(nxt:AudioSegment)
                    WHERE nxt.start_time <= $end_time
                    WITH anchor, before_nodes, collect(DISTINCT nxt) AS after_nodes
                    WITH before_nodes + [anchor] + after_nodes AS all_nodes
                    UNWIND all_nodes AS a
                    WITH DISTINCT a
                    RETURN a.start_time AS timestamp, a.text AS text
                    ORDER BY a.start_time
                    """
                audio_chain_query = audio_chain_query.replace("{hops}", str(max_hops))
                chain_result = session.run(
                    audio_chain_query,
                    anchor_id=anchor["id"],
                    start_time=start_time,
                    end_time=end_time,
                )
                audio_segments = list(chain_result)

        # Fallback to property-based query
        if not audio_segments:
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (a:AudioSegment)
                    WHERE a.video_id = $media_id
                      AND a.start_time >= $start_time
                      AND a.start_time <= $end_time
                    RETURN a.start_time as timestamp, a.text as text
                    ORDER BY a.start_time
                    """,
                    media_id=media_id,
                    start_time=start_time,
                    end_time=end_time,
                )
                audio_segments = list(result)

        # Get scene that contains this timestamp
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (s:Scene)
                WHERE s.video_id = $media_id
                  AND s.start_time <= $timestamp
                  AND s.end_time >= $timestamp
                RETURN s.start_time as start_time, s.end_time as end_time,
                       s.description as description, s.scene_type as scene_type
                LIMIT 1
                """,
                media_id=media_id,
                timestamp=timestamp,
            )
            scene = result.single()

        # Organize context by phase
        before_frames = [f for f in frames if f["timestamp"] < timestamp - 5]
        during_frames = [f for f in frames if timestamp - 5 <= f["timestamp"] <= timestamp + 5]
        after_frames = [f for f in frames if f["timestamp"] > timestamp + 5]

        context = {
            "center_timestamp": timestamp,
            "center_formatted": format_timestamp(timestamp),
            "window": {
                "start": start_time,
                "end": end_time,
                "start_formatted": format_timestamp(start_time),
                "end_formatted": format_timestamp(end_time),
            },
            "current_scene": (
                {
                    "type": scene.get("scene_type") if scene else None,
                    "description": scene.get("description") if scene else None,
                    "time_range": (
                        f"{format_timestamp(scene.get('start_time', 0))} - {format_timestamp(scene.get('end_time', 0))}"
                        if scene
                        else None
                    ),
                }
                if scene
                else None
            ),
            "before": {
                "frames": [
                    {
                        "timestamp": format_timestamp(f["timestamp"]),
                        "description": f["description"][:400] if f["description"] else None,
                    }
                    for f in before_frames[-3:]  # Last 3 before
                ],
            },
            "during": {
                "frames": [
                    {
                        "timestamp": format_timestamp(f["timestamp"]),
                        "description": f["description"][:500] if f["description"] else None,
                    }
                    for f in during_frames
                ],
                "audio": [
                    {
                        "timestamp": format_timestamp(a["timestamp"]),
                        "text": a["text"],
                    }
                    for a in audio_segments
                    if timestamp - 10 <= a["timestamp"] <= timestamp + 10
                ],
            },
            "after": {
                "frames": [
                    {
                        "timestamp": format_timestamp(f["timestamp"]),
                        "description": f["description"][:400] if f["description"] else None,
                    }
                    for f in after_frames[:3]  # First 3 after
                ],
            },
        }

        return {
            "timestamp": timestamp,
            "context": context,
            "total_frames_in_window": len(frames),
            "total_audio_segments": len(audio_segments),
        }

    except Exception as e:
        return {"error": f"Failed to get scene context: {str(e)}", "context": {}}


@tool
async def get_community_overview(
    topic: Annotated[str | None, "Optional topic to filter communities by"] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get thematic community summaries for a video.
    Communities are pre-computed clusters of related entities and content that
    reveal major themes, recurring patterns, and content groupings.
    Use this for overview questions, thematic analysis, or to understand
    the main topics covered before drilling into specifics.
    Optionally filter by topic to find relevant thematic groups.
    """
    if not media_id:
        return {"error": "No video context available.", "communities": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "communities": []}

        communities = kg.get_community_context(media_id, topic=topic)

        if not communities:
            return {
                "message": "No community summaries available for this video.",
                "communities": [],
            }

        return {
            "total_communities": len(communities),
            "filter_topic": topic,
            "communities": [
                {
                    "title": c.get("title", "Untitled"),
                    "summary": c.get("summary", ""),
                    "themes": c.get("themes", []),
                    "member_count": c.get("member_count", 0),
                    "relevance_score": round(c.get("relevance_score", 1.0), 3),
                }
                for c in communities
            ],
        }

    except Exception as e:
        return {"error": f"Failed to get communities: {str(e)}", "communities": []}
