"""
Search Tools
============

LangGraph tools for searching video content.
Includes visual search, entity search, transcript retrieval, and scene description.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp, get_timestamp_from_content
from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice

logger = logging.getLogger(__name__)


@tool
async def search_video(
    query: Annotated[str, "What to search for in the video"],
    content_type: Annotated[str, "Type of content: 'all', 'visual', or 'audio'"] = "all",
    time_range_start: Annotated[float | None, "Start of time range in seconds"] = None,
    time_range_end: Annotated[float | None, "End of time range in seconds"] = None,
    limit: Annotated[int, "Maximum results to return"] = 5,
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video to search. "
        "If omitted, searches the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Primary search tool. Uses hybrid retrieval (semantic, lexical, graph, and reranking)
    to find specific moments, objects, or discussions in the video.
    Returns ranked results with timestamps, descriptions, and relevance scores.
    Filter by content_type or time range to narrow results.
    When several videos are selected, use target_video_id to search a specific video.
    """
    effective_id = target_video_id or media_id
    logger.info(f"search_video called with query='{query}', media_id='{effective_id}'")

    if not effective_id:
        logger.warning("search_video: No media_id provided via InjectedState")
        return tool_error("no_context", "No video context available. Please select a video first.")

    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        # Determine node types
        if content_type == "visual":
            node_types = [NodeType.FRAME, NodeType.SCENE]
        elif content_type == "audio":
            node_types = [NodeType.AUDIO_SEGMENT]
        else:
            node_types = [
                NodeType.FRAME,
                NodeType.AUDIO_SEGMENT,
                NodeType.ENTITY,
                NodeType.COMMUNITY,
            ]

        search_response = await search_service.hybrid_search(
            query_text=query,
            node_types=node_types,
            video_id=effective_id,
            limit=limit * 3,
            expansion_hops=2,
            use_reranking=True,
        )

        results = []
        truncated_fields: list[str] = []

        for r in search_response.results:
            ts = get_timestamp_from_content(r.content)

            if time_range_start is not None and ts < time_range_start:
                continue
            if time_range_end is not None and ts > time_range_end:
                continue

            if r.node_type == NodeType.FRAME:
                desc, was_cut = truncate_with_notice(r.content.get("description", ""), 900)
                if was_cut:
                    truncated_fields.append("content")
                results.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "visual",
                        "content": desc,
                        "score": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                text, was_cut = truncate_with_notice(r.content.get("text", ""), 600)
                if was_cut:
                    truncated_fields.append("content")
                results.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "audio",
                        "content": text,
                        "score": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.ENTITY:
                entity_desc = f"{r.content.get('type', 'entity')}: {r.content.get('name', '')}"
                if r.content.get("description"):
                    entity_desc += f" - {r.content['description'][:200]}"
                if r.content.get("attributes"):
                    attrs = r.content["attributes"]
                    entity_desc += f" [{', '.join(f'{k}={v}' for k,v in attrs.items())}]"
                results.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "entity",
                        "content": entity_desc,
                        "score": round(r.combined_score, 3),
                    }
                )

            if len(results) >= limit:
                break

        return {
            "query": query,
            "total_found": search_response.total_results,
            "results": results,
            "search_time_ms": search_response.vector_search_time_ms,
            "_meta": tool_meta(
                result_count=len(results),
                total_available=search_response.total_results,
                truncated_fields=list(set(truncated_fields)) if truncated_fields else None,
            ),
        }

    except Exception as e:
        logger.error("search_video failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Search failed: {e}")


@tool
async def find_entity(
    entity_name: Annotated[str, "Name of the entity to find"],
    entity_type: Annotated[
        str, "Type: 'person', 'object', 'concept', 'location', or 'any'"
    ] = "any",
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Quick entity lookup — find where a specific person, object, or concept appears.
    Returns timestamps and brief descriptions for each occurrence.
    For a full chronological timeline with rich detail at each
    appearance, use get_entity_timeline instead.
    """
    if not media_id:
        return tool_error("no_context", "No video context available.")

    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        search_response = await search_service.hybrid_search(
            query_text=entity_name,
            node_types=[NodeType.ENTITY, NodeType.FRAME, NodeType.AUDIO_SEGMENT],
            video_id=media_id,
            limit=20,
            expansion_hops=2,
            use_reranking=True,
        )

        occurrences = []
        seen_timestamps: set[float] = set()

        for r in search_response.results:
            ts = get_timestamp_from_content(r.content)
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
                context, _ = truncate_with_notice(r.content.get("description", ""), 500)
                occurrence_type = "visible"
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                context, _ = truncate_with_notice(r.content.get("text", ""), 500)
                occurrence_type = "mentioned"

            occurrences.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "occurrence_type": occurrence_type,
                    "context": context,
                    "confidence": round(r.combined_score, 3),
                }
            )

        occurrences.sort(key=lambda x: x["timestamp"])

        shown = occurrences[:10]
        return {
            "entity": entity_name,
            "entity_type": entity_type,
            "total_occurrences": len(occurrences),
            "occurrences": shown,
            "_meta": tool_meta(
                result_count=len(shown),
                total_available=len(occurrences),
            ),
        }

    except Exception as e:
        logger.error("find_entity failed for %s: %s", media_id, e)
        return tool_error("query_error", f"Entity search failed: {e}")


@tool
async def get_transcript(
    start_time: Annotated[float | None, "Start time in seconds (omit for full transcript)"] = None,
    end_time: Annotated[float | None, "End time in seconds (omit for full transcript)"] = None,
    include_speakers: Annotated[bool, "Include speaker identification if available"] = True,
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video's transcript to retrieve. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get the exact transcript (spoken words/narration) for a video.
    Use this tool to quote verbatim dialogue, narration, or any exact words spoken in the video.
    Omit start_time and end_time to retrieve the full transcript.
    Provide both to retrieve a specific time range.
    Includes speaker identification when available.
    Uses sequential chain traversal when available for seamless cross-boundary retrieval.
    When several videos are selected, use target_video_id to get a specific video's transcript.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return tool_error(
                "graph_unavailable",
                "Knowledge graph is not connected.",
                recovery="Try get_video_info for basic metadata from database.",
            )

        full_transcript = start_time is None and end_time is None
        effective_start = start_time if start_time is not None else 0.0
        effective_end = end_time if end_time is not None else 999999.0

        # Delegate to service layer (handles chain-walk + fallback)
        segments = kg.get_transcript_segments(
            effective_id,
            start_time=None if full_transcript else effective_start,
            end_time=None if full_transcript else effective_end,
        )

        if not segments:
            return {
                "start_time": effective_start,
                "end_time": effective_end if not full_transcript else None,
                "transcript": "",
                "message": "No transcript found for this video. It may not have audio transcription.",
                "_meta": tool_meta(is_complete=True, result_count=0),
            }

        transcript_parts = []
        speakers_found: set[str] = set()

        for seg in segments:
            ts = format_timestamp(seg.get("timestamp", 0))
            text = seg.get("text", "")
            speaker = seg.get("speaker")

            if include_speakers and speaker:
                speakers_found.add(speaker)
                transcript_parts.append(f"[{ts}] **{speaker}**: {text}")
            else:
                transcript_parts.append(f"[{ts}] {text}")

        return {
            "start_time": effective_start,
            "end_time": effective_end if not full_transcript else None,
            "start_formatted": format_timestamp(effective_start),
            "end_formatted": format_timestamp(effective_end) if not full_transcript else None,
            "transcript": "\n".join(transcript_parts),
            "segments_count": len(segments),
            "speakers": list(speakers_found) if include_speakers else [],
            "has_speaker_ids": len(speakers_found) > 0,
            "_meta": tool_meta(result_count=len(segments)),
        }

    except Exception as e:
        logger.error("get_transcript failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to get transcript: {e}")


@tool
async def describe_scene(
    timestamp: Annotated[float, "Timestamp in seconds to describe"],
    target_video_id: Annotated[
        str | None,
        "When several videos are selected, specify which video to describe. "
        "If omitted, uses the primary (first) video.",
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
) -> dict[str, Any]:
    """
    Point-in-time visual lookup — shows what is happening at a specific timestamp
    by returning the nearest frame's detailed description. Reports the actual
    frame timestamp and gap if it differs from the requested time.
    When several videos are selected, use target_video_id to describe a scene from a specific video.
    """
    effective_id = target_video_id or media_id
    if not effective_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return tool_error(
                "graph_unavailable",
                "Knowledge graph is not connected.",
                recovery="Try get_video_info for basic metadata from database.",
            )

        frame = kg.get_nearest_frame(effective_id, timestamp, user_id=user_id)

        if not frame:
            return {
                "timestamp": timestamp,
                "description": "No frame data available for this timestamp.",
                "_meta": tool_meta(is_complete=False, result_count=0),
            }

        actual_ts = frame.get("timestamp", timestamp)
        gap = abs(actual_ts - timestamp)

        result: dict[str, Any] = {
            "timestamp": actual_ts,
            "timestamp_formatted": format_timestamp(actual_ts),
            "description": frame.get("description") or "No description available.",
            "_meta": tool_meta(),
        }
        if gap > 1.0:
            result["requested_timestamp"] = timestamp
            result["gap_seconds"] = round(gap, 2)

        return result

    except Exception as e:
        logger.error("describe_scene failed for %s: %s", effective_id, e)
        return tool_error("query_error", f"Failed to describe scene: {e}")
