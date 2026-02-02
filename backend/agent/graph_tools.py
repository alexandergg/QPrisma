"""
LangGraph Tools
===============

Tools for the video agent using LangGraph @tool decorator.
Uses InjectedToolArg for proper context injection from RunnableConfig.
"""

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from agent.tools.base import format_timestamp

# =============================================================================
# Search Tools
# =============================================================================


@tool
async def search_video(
    query: Annotated[str, "What to search for in the video"],
    content_type: Annotated[
        str, "Type of content: 'all', 'visual', or 'audio'"
    ] = "all",
    time_range_start: Annotated[float | None, "Start of time range in seconds"] = None,
    time_range_end: Annotated[float | None, "End of time range in seconds"] = None,
    limit: Annotated[int, "Maximum results to return"] = 5,
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Search for specific moments, topics, objects, or spoken words in the video.
    Returns timestamped results with descriptions.
    """
    if not media_id:
        return {"error": "No video context available. Please select a video first.", "results": []}

    try:
        from api.dependencies import get_graph_search_service
        from models.graph_models import NodeType

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        # Determine node types
        if content_type == "visual":
            node_types = [NodeType.FRAME, NodeType.SCENE]
        elif content_type == "audio":
            node_types = [NodeType.AUDIO_SEGMENT]
        else:
            node_types = [NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY]

        search_response = search_service.hybrid_search(
            query_text=query,
            node_types=node_types,
            video_id=media_id,
            limit=limit * 2,
            expansion_hops=1,
            use_reranking=True,
        )

        results = []
        for r in search_response.results:
            ts = r.content.get("timestamp", 0)

            if time_range_start is not None and ts < time_range_start:
                continue
            if time_range_end is not None and ts > time_range_end:
                continue

            if r.node_type == NodeType.FRAME:
                results.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "visual",
                    "content": r.content.get("description", "")[:300],
                    "score": round(r.combined_score, 3),
                })
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                results.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "audio",
                    "content": r.content.get("text", "")[:300],
                    "score": round(r.combined_score, 3),
                })
            elif r.node_type == NodeType.ENTITY:
                results.append({
                    "timestamp": ts or 0,
                    "timestamp_formatted": format_timestamp(ts or 0),
                    "type": "entity",
                    "content": f"{r.content.get('type', 'entity')}: {r.content.get('name', '')}",
                    "score": round(r.combined_score, 3),
                })

            if len(results) >= limit:
                break

        return {
            "query": query,
            "total_found": search_response.total_results,
            "results": results,
            "search_time_ms": search_response.vector_search_time_ms,
        }

    except Exception as e:
        return {"error": f"Search failed: {str(e)}", "results": []}


@tool
async def find_entity(
    entity_name: Annotated[str, "Name of the entity to find"],
    entity_type: Annotated[
        str, "Type: 'person', 'object', 'concept', 'location', or 'any'"
    ] = "any",
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Find all occurrences of a specific person, object, or concept in the video.
    Returns timestamps where the entity appears or is mentioned.
    """
    if not media_id:
        return {"error": "No video context available.", "occurrences": []}

    try:
        from api.dependencies import get_graph_search_service
        from models.graph_models import NodeType

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        search_response = search_service.hybrid_search(
            query_text=entity_name,
            node_types=[NodeType.ENTITY, NodeType.FRAME, NodeType.AUDIO_SEGMENT],
            video_id=media_id,
            limit=20,
            expansion_hops=2,
            use_reranking=True,
        )

        occurrences = []
        seen_timestamps = set()

        for r in search_response.results:
            ts = r.content.get("timestamp", 0)
            ts_key = round(ts, 1)
            if ts_key in seen_timestamps:
                continue
            seen_timestamps.add(ts_key)

            context = ""
            occurrence_type = "mentioned"

            if r.node_type == NodeType.ENTITY:
                if entity_type != "any" and r.content.get("type", "").lower() != entity_type:
                    continue
                context = f"Entity '{r.content.get('name')}' of type {r.content.get('type')}"
                occurrence_type = "identified"
            elif r.node_type == NodeType.FRAME:
                context = r.content.get("description", "")[:200]
                occurrence_type = "visible"
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                context = r.content.get("text", "")[:200]
                occurrence_type = "mentioned"

            occurrences.append({
                "timestamp": ts,
                "timestamp_formatted": format_timestamp(ts),
                "occurrence_type": occurrence_type,
                "context": context,
                "confidence": round(r.combined_score, 3),
            })

        occurrences.sort(key=lambda x: x["timestamp"])

        return {
            "entity": entity_name,
            "entity_type": entity_type,
            "total_occurrences": len(occurrences),
            "occurrences": occurrences[:10],
        }

    except Exception as e:
        return {"error": f"Entity search failed: {str(e)}", "occurrences": []}


@tool
async def get_transcript(
    start_time: Annotated[float, "Start time in seconds"],
    end_time: Annotated[float, "End time in seconds"],
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Get the transcript (spoken words) for a specific time range in the video.
    """
    if not media_id:
        return {"error": "No video context available.", "transcript": ""}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        segments = db.get_audio_segments(media_id, start_time, end_time)

        if not segments:
            return {
                "start_time": start_time,
                "end_time": end_time,
                "transcript": "",
                "message": "No transcript found for this time range.",
            }

        transcript_parts = []
        for seg in segments:
            ts = format_timestamp(seg.timestamp)
            transcript_parts.append(f"[{ts}] {seg.text}")

        return {
            "start_time": start_time,
            "end_time": end_time,
            "start_formatted": format_timestamp(start_time),
            "end_formatted": format_timestamp(end_time),
            "transcript": "\n".join(transcript_parts),
            "segments_count": len(segments),
        }

    except Exception as e:
        return {"error": f"Failed to get transcript: {str(e)}", "transcript": ""}


@tool
async def describe_scene(
    timestamp: Annotated[float, "Timestamp in seconds to describe"],
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Get a detailed visual description of what's happening at a specific timestamp.
    """
    if not media_id:
        return {"error": "No video context available.", "description": ""}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        frame = db.get_nearest_frame(media_id, timestamp)

        if not frame:
            return {
                "timestamp": timestamp,
                "description": "No frame data available for this timestamp.",
            }

        return {
            "timestamp": frame.timestamp,
            "timestamp_formatted": format_timestamp(frame.timestamp),
            "description": frame.gpt_description or "No description available.",
            "detected_objects": frame.detected_objects or [],
            "detected_text": frame.detected_text,
        }

    except Exception as e:
        return {"error": f"Failed to describe scene: {str(e)}", "description": ""}


@tool
async def list_chapters(
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Get the chapter structure and overview of the video.
    """
    if not media_id:
        return {"error": "No video context available.", "chapters": []}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        chapters = db.get_chapters(media_id)

        if not chapters:
            return {"message": "No chapters found for this video.", "chapters": []}

        return {
            "total_chapters": len(chapters),
            "chapters": [
                {
                    "number": i + 1,
                    "title": ch.title,
                    "start_time": ch.start_time,
                    "start_formatted": format_timestamp(ch.start_time),
                    "end_time": ch.end_time,
                    "end_formatted": format_timestamp(ch.end_time),
                    "summary": ch.summary,
                }
                for i, ch in enumerate(chapters)
            ],
        }

    except Exception as e:
        return {"error": f"Failed to get chapters: {str(e)}", "chapters": []}


@tool
async def get_video_info(
    media_id: Annotated[str | None, InjectedToolArg] = None,
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
    media_id: Annotated[str | None, InjectedToolArg] = None,
) -> dict[str, Any]:
    """
    Get a summary of the video content at different levels of detail.
    """
    if not media_id:
        return {"error": "No video context available.", "summary": ""}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        media = db.get_media(media_id)

        if not media:
            return {"error": "Video not found.", "summary": ""}

        summary = media.summary or "No summary available for this video."

        return {
            "level": level,
            "summary": summary,
            "title": media.original_filename or media.blob_name,
        }

    except Exception as e:
        return {"error": f"Failed to get summary: {str(e)}", "summary": ""}


# =============================================================================
# Tool Collections
# =============================================================================

SEARCH_TOOLS = [
    search_video,
    find_entity,
    get_transcript,
    describe_scene,
    list_chapters,
    get_video_info,
    get_summary,
]

# Note: Editor tools will be added separately for the EditorAgent graph
