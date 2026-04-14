"""
Context Tools
=============

LangGraph tools for retrieving video context, chapters, summaries, and metadata.
"""

import asyncio
import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp
from agent.utils.text import SCENE_DESCRIPTION_PREFIXES, clean_generated_text, is_valid_content
from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice

logger = logging.getLogger(__name__)


def _generate_scene_title(scene: dict) -> str | None:
    """Generate a scene title from the scene node's own properties.

    Uses ``scene.title`` directly when available, otherwise derives a short
    title from the first sentence of ``scene.description``.  No frame data is
    needed — scene properties are populated during ingestion.
    """
    title = scene.get("title")
    if title:
        return title

    description = scene.get("description", "")
    if description:
        clean_desc = clean_generated_text(description, SCENE_DESCRIPTION_PREFIXES)
        if clean_desc:
            first_sentence = clean_desc.split(".")[0][:100]
            return first_sentence.strip() or None
    return None


def _generate_scene_summary(scene: dict) -> str | None:
    """Return the scene's own description as its summary.

    Scene descriptions are set during ingestion and are already concise
    natural-language summaries — no reformatting or truncation is applied
    beyond stripping common prefixes.
    """
    summary = scene.get("description")
    if summary:
        clean_summary = clean_generated_text(summary, SCENE_DESCRIPTION_PREFIXES)
        return clean_summary or None
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


def _build_scene_list(scenes: list[dict]) -> list[dict[str, Any]]:
    """Build a compact scene index directly from scene node properties.

    Each entry contains the scene's index, title, time range, and brief
    summary — all derived from the scene node itself (no frame data needed).
    This eliminates the previous 500-frame cap that left later scenes empty
    for long videos.
    """
    scene_list = []
    for s in scenes:
        start = float(s.get("start_time", 0) or 0)
        end = float(s.get("end_time", 0) or 0)

        scene_title = _generate_scene_title(s)
        scene_summary = _generate_scene_summary(s)

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
    """Group scenes into chapters with embedded compact scene entries."""
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

        # Embed compact scene entries so the LLM sees the full hierarchy
        compact_scenes = [
            {
                "scene_id": s["scene_id"],
                "title": s["title"],
                "time_range": (
                    f"{format_timestamp(s['start_time'])} - " f"{format_timestamp(s['end_time'])}"
                ),
            }
            for s in chunk
        ]

        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": chapter_title,
                "summary": chapter_summary,
                "start_time": chunk[0]["start_time"],
                "end_time": chunk[-1]["end_time"],
                "duration": max(0.0, chunk[-1]["end_time"] - chunk[0]["start_time"]),
                "scene_count": len(chunk),
                "scenes": compact_scenes,
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

    formatted: dict[str, Any] = {
        "number": number,
        "title": title,
        "start_time": start_time,
        "start_formatted": format_timestamp(start_time),
        "end_time": end_time,
        "end_formatted": format_timestamp(end_time),
        "summary": summary,
    }
    # Pass through compact scene entries from chapters
    if "scenes" in entry:
        formatted["scenes"] = entry["scenes"]
    return formatted


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
    Get the chronological chapter/timeline structure of the entire video.

    Returns a compact index of ALL scenes grouped into chapters. Each chapter
    includes a title, time range, summary, and its constituent scenes.
    Every scene is represented with a title and time range — no scenes are
    omitted regardless of video length.

    **When to use:**
    - User asks for a timeline, table-of-contents, or chapter breakdown
    - User asks "what happens in the video?" or "show me the structure"
    - You need to orient yourself within the video before drilling down

    **For deeper detail on a specific scene**, use the scene drill-down
    tool with a timestamp (see ``_meta.detail_hint`` for the call).

    For a single synopsis, use get_summary instead.
    For thematic topic clusters, use get_community_overview.
    When several videos are selected, use target_video_id.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        video_node = await asyncio.to_thread(kg.get_video_node, effective_id)
        if not video_node:
            return {
                "message": "Video not found in knowledge graph.",
                "chapters": [],
                "_meta": tool_meta(is_complete=False, result_count=0),
            }

        scenes = await asyncio.to_thread(kg.get_video_scenes, effective_id)
        if not scenes:
            summary, topics = await asyncio.to_thread(kg.get_video_summary, effective_id)
            result: dict[str, Any] = {
                "chapters": [],
                "_meta": tool_meta(is_complete=True, result_count=0),
            }
            if topics:
                result["message"] = "No chapters found, but here are the main topics covered:"
                result["topics"] = topics
            else:
                result["message"] = "No chapters found for this video."
            if summary:
                result["summary"] = summary
            return result

        # Build scene list from scene node properties — no bulk frame fetch
        scene_list = _build_scene_list(scenes)
        chapters = _build_chapters(scene_list)

        # Video summary: prefer the pre-computed summary on the video node
        video_summary = video_node.get("summary")
        if not video_summary:
            # Fallback: sample a few frames for summary generation
            sample_frames = await asyncio.to_thread(kg.get_video_frames, effective_id)
            video_summary = _generate_video_summary(video_node, sample_frames[:100])

        key_topics = _extract_key_topics(video_node)

        entries = chapters if len(chapters) > 1 else scene_list
        response: dict[str, Any] = {
            "total_chapters": len(entries),
            "total_scenes": len(scene_list),
            "chapters": [_format_chapter_entry(e, i + 1) for i, e in enumerate(entries)],
            "_meta": tool_meta(
                result_count=len(entries),
                total_available=len(entries),
                detail_hint=(
                    "Use get_scene_context(timestamp=<start_seconds>) for detailed "
                    "visual descriptions, detected objects, and frame-level analysis "
                    "of any specific scene."
                ),
            ),
        }

        if video_summary:
            response["video_summary"] = video_summary
        if key_topics:
            response["topics"] = key_topics

        return response

    except Exception as e:
        logger.error("list_chapters failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get chapters: {e}")


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
    Get basic info about a video: title, duration, resolution, fps, and processing status.
    Database-backed — works even when the knowledge graph is unavailable.
    When several videos are selected, use target_video_id to get info for a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        media = db.get_media(effective_id)

        if not media:
            return tool_error("no_data", "Video not found.")

        metadata = media.video_metadata or {}

        return {
            "media_id": effective_id,
            "title": media.original_filename or media.blob_name,
            "duration": metadata.get("duration", 0),
            "duration_formatted": format_timestamp(metadata.get("duration", 0)),
            "resolution": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
            "fps": metadata.get("fps", 0),
            "status": media.processing_status,
            "_meta": tool_meta(source="database"),
        }

    except Exception as e:
        logger.error("get_video_info failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get video info: {e}")


@tool
async def get_summary(
    level: Annotated[
        str, "Hint for response style: 'brief', 'detailed', or 'comprehensive'"
    ] = "brief",
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video to summarize. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
) -> dict[str, Any]:
    """
    Get a single synopsis summary of the video with title, topics, and duration.
    The level parameter hints at desired response verbosity but the underlying data
    is the same. For chronological chapter breakdown, use list_chapters instead.
    For thematic topic clusters, use get_community_overview.
    When several videos are selected, use target_video_id to summarize a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        record = await asyncio.to_thread(
            lambda: kg.get_video_summary_data(effective_id, user_id=user_id)
        )

        if not record or not record.get("summary"):
            return {
                "level": level,
                "summary": "No summary available for this video.",
                "title": record.get("title") if record else "Unknown",
                "_meta": tool_meta(source="graph", is_complete=False),
            }

        duration = record.get("duration", 0)

        return {
            "level": level,
            "summary": record.get("summary", ""),
            "title": record.get("title", ""),
            "topics": record.get("topics") or [],
            "duration_formatted": format_timestamp(duration) if duration else None,
            "_meta": tool_meta(),
        }

    except Exception as e:
        logger.error("get_summary failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get summary: {e}")


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
    Get comprehensive context around a specific moment in the video using a time window.
    Returns frames and audio organized as before/during/after phases around the timestamp.
    Use this for understanding what happened before, during, and after a moment.
    For a single frame description at one point, use describe_scene instead.
    Uses temporal chain traversal when available for seamless cross-scene context.
    When several videos are selected, use target_video_id to examine a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        start_time = max(0, timestamp - window_seconds)
        end_time = timestamp + window_seconds

        # Delegate all raw Cypher to service layer
        frames = await asyncio.to_thread(
            kg.get_frames_in_window, effective_id, start_time, end_time, timestamp
        )
        audio_segments = await asyncio.to_thread(
            kg.get_audio_in_window, effective_id, start_time, end_time, timestamp
        )
        scene = await asyncio.to_thread(kg.get_scene_at_timestamp, effective_id, timestamp)

        # Organize context by phase
        before_frames = [f for f in frames if f["timestamp"] < timestamp - 5]
        during_frames = [f for f in frames if timestamp - 5 <= f["timestamp"] <= timestamp + 5]
        after_frames = [f for f in frames if f["timestamp"] > timestamp + 5]

        truncated_fields: list[str] = []

        def _trunc_desc(desc: str | None, limit: int) -> str | None:
            if not desc:
                return None
            text, was_cut = truncate_with_notice(desc, limit)
            if was_cut:
                truncated_fields.append("description")
            return text

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
                        f"{format_timestamp(scene.get('start_time', 0))} - "
                        f"{format_timestamp(scene.get('end_time', 0))}"
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
                        "description": _trunc_desc(f["description"], 400),
                    }
                    for f in before_frames[-3:]
                ],
            },
            "during": {
                "frames": [
                    {
                        "timestamp": format_timestamp(f["timestamp"]),
                        "description": _trunc_desc(f["description"], 500),
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
                        "description": _trunc_desc(f["description"], 400),
                    }
                    for f in after_frames[:3]
                ],
            },
        }

        return {
            "timestamp": timestamp,
            "context": context,
            "total_frames_in_window": len(frames),
            "total_audio_segments": len(audio_segments),
            "_meta": tool_meta(
                result_count=len(frames) + len(audio_segments),
                truncated_fields=list(set(truncated_fields)) if truncated_fields else None,
            ),
        }

    except Exception as e:
        logger.error("get_scene_context failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get scene context: {e}")


@tool
async def get_community_overview(
    topic: Annotated[str | None, "Optional topic to filter communities by"] = None,
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video's communities to retrieve. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get thematic community summaries for a video.
    Communities are pre-computed clusters of related entities and content that
    reveal major themes, recurring patterns, and content groupings.
    Returns clusters with titles, summaries, theme lists, and member counts.
    Use this for overview questions, thematic analysis, or to understand
    the main topics covered before drilling into specifics.
    For a single synopsis, use get_summary. For chronological structure, use list_chapters.
    Optionally filter by topic to find relevant thematic groups.
    When several videos are selected, use target_video_id to get communities for a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        communities = await asyncio.to_thread(
            lambda: kg.get_community_context(effective_id, topic=topic)
        )

        if not communities:
            return {
                "message": "No community summaries available for this video.",
                "communities": [],
                "_meta": tool_meta(is_complete=True, result_count=0),
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
            "_meta": tool_meta(result_count=len(communities)),
        }

    except Exception as e:
        logger.error("get_community_overview failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get communities: {e}")
