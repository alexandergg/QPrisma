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

logger = logging.getLogger(__name__)


@tool
async def search_video(
    query: Annotated[str, "What to search for in the video"],
    content_type: Annotated[str, "Type of content: 'all', 'visual', or 'audio'"] = "all",
    time_range_start: Annotated[float | None, "Start of time range in seconds"] = None,
    time_range_end: Annotated[float | None, "End of time range in seconds"] = None,
    limit: Annotated[int, "Maximum results to return"] = 5,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Search for specific moments, topics, objects, or spoken words in the video.
    Returns timestamped results with descriptions.
    """
    logger.info(f"search_video called with query='{query}', media_id='{media_id}'")

    if not media_id:
        logger.warning("search_video: No media_id provided via InjectedState")
        return {"error": "No video context available. Please select a video first.", "results": []}

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
            video_id=media_id,
            limit=limit * 3,
            expansion_hops=2,
            use_reranking=True,
        )

        results = []
        for r in search_response.results:
            ts = get_timestamp_from_content(r.content)

            if time_range_start is not None and ts < time_range_start:
                continue
            if time_range_end is not None and ts > time_range_end:
                continue

            if r.node_type == NodeType.FRAME:
                results.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "visual",
                        "content": r.content.get("description", "")[:900],
                        "score": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                results.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "audio",
                        "content": r.content.get("text", "")[:600],
                        "score": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.ENTITY:
                # Include entity attributes for richer context
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
        }

    except Exception as e:
        return {"error": f"Search failed: {str(e)}", "results": []}


@tool
async def find_entity(
    entity_name: Annotated[str, "Name of the entity to find"],
    entity_type: Annotated[
        str, "Type: 'person', 'object', 'concept', 'location', or 'any'"
    ] = "any",
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Find all occurrences of a specific person, object, or concept in the video.
    Returns timestamps where the entity appears or is mentioned.
    """
    if not media_id:
        return {"error": "No video context available.", "occurrences": []}

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
        seen_timestamps = set()

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
                context = r.content.get("description", "")[:500]
                occurrence_type = "visible"
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                context = r.content.get("text", "")[:500]
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
    include_speakers: Annotated[bool, "Include speaker identification if available"] = True,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get the transcript (spoken words) for a specific time range in the video.
    Includes speaker identification when available.
    """
    if not media_id:
        return {"error": "No video context available.", "transcript": ""}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "transcript": ""}

        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $media_id
                  AND a.start_time >= $start_time
                  AND a.start_time <= $end_time
                RETURN a.start_time as timestamp, a.text as text,
                       a.speaker as speaker, a.confidence as confidence
                ORDER BY a.start_time
                """,
                media_id=media_id,
                start_time=start_time,
                end_time=end_time,
            )
            segments = list(result)

        if not segments:
            return {
                "start_time": start_time,
                "end_time": end_time,
                "transcript": "",
                "message": "No transcript found for this time range. This video may not have audio transcription.",
            }

        transcript_parts = []
        speakers_found = set()

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
            "start_time": start_time,
            "end_time": end_time,
            "start_formatted": format_timestamp(start_time),
            "end_formatted": format_timestamp(end_time),
            "transcript": "\n".join(transcript_parts),
            "segments_count": len(segments),
            "speakers": list(speakers_found) if include_speakers else [],
            "has_speaker_ids": len(speakers_found) > 0,
        }

    except Exception as e:
        return {"error": f"Failed to get transcript: {str(e)}", "transcript": ""}


@tool
async def describe_scene(
    timestamp: Annotated[float, "Timestamp in seconds to describe"],
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get a detailed visual description of what's happening at a specific timestamp.
    """
    if not media_id:
        return {"error": "No video context available.", "description": ""}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        if not kg.is_connected:
            return {"error": "Knowledge graph not available.", "description": ""}

        # Find the nearest frame to the requested timestamp
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $media_id
                RETURN f.timestamp as timestamp, f.description as description,
                       f.detected_objects as detected_objects, f.detected_text as detected_text
                ORDER BY abs(f.timestamp - $timestamp)
                LIMIT 1
                """,
                media_id=media_id,
                timestamp=timestamp,
            )
            frame = result.single()

        if not frame:
            return {
                "timestamp": timestamp,
                "description": "No frame data available for this timestamp.",
            }

        return {
            "timestamp": frame.get("timestamp", timestamp),
            "timestamp_formatted": format_timestamp(frame.get("timestamp", timestamp)),
            "description": frame.get("description") or "No description available.",
            "detected_objects": frame.get("detected_objects") or [],
            "detected_text": frame.get("detected_text"),
        }

    except Exception as e:
        return {"error": f"Failed to describe scene: {str(e)}", "description": ""}
