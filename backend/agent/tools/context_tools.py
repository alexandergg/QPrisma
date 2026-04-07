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
from agent.utils.text import SCENE_DESCRIPTION_PREFIXES, clean_generated_text, is_valid_content

logger = logging.getLogger(__name__)


def _generate_scene_title(scene: dict, scene_frames: list[dict]) -> str | None:
    """Generate a scene title from its first frame description."""
    title = scene.get("title")
    if title:
        return title

    if not scene_frames:
        return None

    first_desc = scene_frames[0].get("description", "")
    if not first_desc:
        return None

    clean_desc = clean_generated_text(first_desc, SCENE_DESCRIPTION_PREFIXES)
    if clean_desc:
        first_sentence = clean_desc.split(".")[0][:100]
        return first_sentence.strip()
    return None


def _generate_scene_summary(scene: dict, scene_frames: list[dict]) -> str | None:
    """Generate a scene summary from its description or frame descriptions."""
    summary = scene.get("description")
    if summary:
        clean_summary = clean_generated_text(summary, SCENE_DESCRIPTION_PREFIXES)
        return clean_summary or None

    if not scene_frames:
        return None

    descriptions = [
        clean_generated_text(f.get("description", ""), SCENE_DESCRIPTION_PREFIXES)
        for f in scene_frames[:3]
        if f.get("description")
    ]
    descriptions = [d for d in descriptions if d]
    if descriptions:
        return " ".join(descriptions)[:500]
    return None


def _generate_video_summary(video_node: dict, all_frames: list[dict]) -> str | None:
    """Generate a video summary from the video node or sampled frame descriptions."""
    from agent.utils.text import VIDEO_SUMMARY_PREFIXES

    video_summary = video_node.get("summary")
    if video_summary:
        return video_summary

    valid_frames = [f for f in all_frames if is_valid_content(f.get("description", ""))]
    if not valid_frames:
        return None

    sample_count = min(5, len(valid_frames))
    step = max(1, len(valid_frames) // sample_count)
    sampled = [valid_frames[i] for i in range(0, len(valid_frames), step)][:sample_count]

    summaries = []
    for f in sampled:
        desc = f.get("description", "")
        clean = clean_generated_text(desc, VIDEO_SUMMARY_PREFIXES)
        if clean:
            summaries.append(clean[:150])

    return " ".join(summaries)[:600] if summaries else None


def _extract_key_topics(video_node: dict) -> list[str]:
    """Extract key topics from the video node."""
    return video_node.get("topics") or []


def _build_scene_list(
    scenes: list[dict], all_frames: list[dict]
) -> list[dict[str, Any]]:
    """Build enriched scene list with titles and summaries from graph data."""
    scene_list = []
    for s in scenes:
        start = float(s.get("start_time", 0) or 0)
        end = float(s.get("end_time", 0) or 0)

        scene_frames = [
            f
            for f in all_frames
            if f.get("timestamp") is not None and start <= f["timestamp"] < end
        ]

        scene_title = _generate_scene_title(s, scene_frames)
        scene_summary = _generate_scene_summary(s, scene_frames)

        scene_list.append(
            {
                "scene_id": int(s.get("scene_index", 0) or 0),
                "start_time": start,
                "end_time": end,
                "title": scene_title or f"Scene {int(s.get('scene_index', 0) or 0) + 1}",
                "summary": scene_summary,
            }
        )
    return scene_list


def _build_chapters(scene_list: list[dict], max_scenes_per_chapter: int = 5) -> list[dict]:
    """Group scenes into chapters."""
    chapters = []
    for i in range(0, len(scene_list), max_scenes_per_chapter):
        chunk = scene_list[i : i + max_scenes_per_chapter]
        if not chunk:
            continue
        chapter_id = len(chapters)

        first_scene_title = chunk[0].get("title", "")
        chapter_title = first_scene_title[:60] if first_scene_title else f"Part {chapter_id + 1}"

        scene_summaries = [s.get("summary", "") for s in chunk if s.get("summary")]
        chapter_summary = " ".join(scene_summaries)[:300] if scene_summaries else None

        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": chapter_title,
                "summary": chapter_summary,
                "start_time": chunk[0]["start_time"],
                "end_time": chunk[-1]["end_time"],
                "duration": max(0.0, chunk[-1]["end_time"] - chunk[0]["start_time"]),
                "scene_count": len(chunk),
            }
        )
    return chapters


def _format_chapter_entry(entry: dict[str, Any], number: int) -> dict[str, Any]:
    """Format a scene or chapter entry into the list_chapters response shape."""
    start_time = float(entry.get("start_time", 0) or 0)
    end_time = float(entry.get("end_time", start_time) or start_time)

    title = entry.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        title = f"Scene {number}"

    summary = entry.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    if not summary:
        summary = title

    return {
        "number": number,
        "title": title,
        "start_time": start_time,
        "start_formatted": format_timestamp(start_time),
        "end_time": end_time,
        "end_formatted": format_timestamp(end_time),
        "summary": summary,
    }


@tool
async def list_chapters(
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video's chapters to retrieve. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get the chapter structure and timeline overview of the video.
    Returns scenes grouped into chapters with titles, summaries, and timestamps.
    When several videos are selected, use target_video_id to get chapters for a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return {"error": "No video context available.", "chapters": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            logger.warning("list_chapters: Neo4j unavailable at %s", getattr(kg, "uri", "unknown"))
            return {"error": "Knowledge graph not available.", "chapters": []}

        video_node = kg.get_video_node(effective_id)
        if not video_node:
            return {"message": "Video not found in knowledge graph.", "chapters": []}

        scenes = kg.get_video_scenes(effective_id)
        if not scenes:
            # No scenes — return video-level info as fallback
            summary, topics = kg.get_video_summary(effective_id)
            result: dict[str, Any] = {"chapters": []}
            if topics:
                result["message"] = "No chapters found, but here are the main topics covered:"
                result["topics"] = topics
            else:
                result["message"] = "No chapters found for this video."
            if summary:
                result["summary"] = summary
            return result

        all_frames = kg.get_video_frames(effective_id)
        scene_list = _build_scene_list(scenes, all_frames)
        chapters = _build_chapters(scene_list)

        video_summary = _generate_video_summary(video_node, all_frames)
        key_topics = _extract_key_topics(video_node)

        # Build response using chapters (or scenes if only 1 chapter)
        entries = chapters if len(chapters) > 1 else scene_list
        response: dict[str, Any] = {
            "total_chapters": len(entries),
            "chapters": [_format_chapter_entry(e, i + 1) for i, e in enumerate(entries)],
        }

        if video_summary:
            response["video_summary"] = video_summary
        if key_topics:
            response["topics"] = key_topics

        return response

    except Exception as e:
        logger.error("list_chapters failed for %s: %s", effective_id, e)
        return {"error": f"Failed to get chapters: {str(e)}", "chapters": []}


@tool
async def get_video_info(
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video's info to retrieve. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get basic information about a video (title, duration, etc.).
    When several videos are selected, use target_video_id to get info for a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return {"error": "No video context available."}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        media = db.get_media(effective_id)

        if not media:
            return {"error": "Video not found."}

        metadata = media.video_metadata or {}

        return {
            "media_id": effective_id,
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
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video to summarize. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get a summary of the video content at different levels of detail.
    When several videos are selected, use target_video_id to summarize a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return {"error": "No video context available.", "summary": ""}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            logger.warning("get_summary: Neo4j unavailable at %s", kg.uri)
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
                media_id=effective_id,
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
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video's scene to examine. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get comprehensive context around a specific moment in the video.
    Returns frames, audio, and scene information within the time window.
    Use this for understanding what happened before, during, and after a moment.
    Uses temporal chain traversal when available for seamless cross-scene context.
    When several videos are selected, use target_video_id to examine a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
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
                media_id=effective_id,
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
                    media_id=effective_id,
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
                media_id=effective_id,
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
                    media_id=effective_id,
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
                media_id=effective_id,
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
