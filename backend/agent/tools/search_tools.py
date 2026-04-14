"""
Search Tools
============

LangGraph tools for searching video content.
Includes visual search, entity search, transcript retrieval, and scene description.
"""

import asyncio
import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp, get_timestamp_from_content
from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice

logger = logging.getLogger(__name__)

# Timeout for hybrid search (embedding + vector + fulltext + reranking).
# Prevents indefinite hangs when Azure OpenAI embedding endpoint is slow.
_HYBRID_SEARCH_TIMEOUT_S = 30.0


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
    logger.info("search_video called | query='%s' media_id='%s'", query, effective_id)

    if not effective_id:
        logger.warning("search_video: No media_id provided via InjectedState")
        return tool_error("no_context", "No video context available. Please select a video first.")

    try:
        (
            results,
            total_found,
            search_time_ms,
            truncated_fields,
            search_mode,
        ) = await _hybrid_search_with_fallback(
            query=query,
            video_id=effective_id,
            content_type=content_type,
            limit=limit,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

        logger.info(
            "search_video completed | mode=%s results=%d total=%d time_ms=%.0f",
            search_mode,
            len(results),
            total_found,
            search_time_ms,
        )

        meta_kwargs: dict[str, Any] = {
            "result_count": len(results),
            "total_available": total_found,
            "detail_hint": (
                "Use get_scene_context(timestamp=<seconds>) to get full visual "
                "descriptions, detected objects, and audio around any result."
            ),
        }
        if truncated_fields:
            meta_kwargs["truncated_fields"] = list(set(truncated_fields))

        payload: dict[str, Any] = {
            "query": query,
            "total_found": total_found,
            "results": results,
            "search_time_ms": search_time_ms,
            "_meta": tool_meta(**meta_kwargs),
        }
        if search_mode == "keyword_fallback":
            payload["search_mode"] = "keyword_fallback"
        return payload

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

    logger.info(
        "find_entity called | entity='%s' type='%s' media_id='%s'",
        entity_name,
        entity_type,
        media_id,
    )

    try:
        occurrences: list[dict[str, Any]] = []
        search_mode = "hybrid"

        # Try hybrid search with timeout, fall back to graph-only lookup
        try:
            from models.graph_models import NodeType
            from services.graph_search_service import get_graph_search_service

            search_service = get_graph_search_service()
            search_response = await asyncio.wait_for(
                search_service.hybrid_search(
                    query_text=entity_name,
                    node_types=[NodeType.ENTITY, NodeType.FRAME, NodeType.AUDIO_SEGMENT],
                    video_id=media_id,
                    limit=20,
                    expansion_hops=2,
                    use_reranking=True,
                ),
                timeout=_HYBRID_SEARCH_TIMEOUT_S,
            )

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

        except (TimeoutError, Exception) as exc:
            logger.warning(
                "find_entity: hybrid search failed (%s), falling back to graph lookup",
                type(exc).__name__,
            )
            search_mode = "graph_fallback"
            occurrences = await _entity_graph_fallback(entity_name, media_id, entity_type)

        occurrences.sort(key=lambda x: x["timestamp"])
        shown = occurrences[:10]

        logger.info(
            "find_entity completed | mode=%s entity='%s' results=%d",
            search_mode,
            entity_name,
            len(shown),
        )

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

        full_transcript = start_time is None and end_time is None
        effective_start = start_time if start_time is not None else 0.0
        effective_end = end_time if end_time is not None else 999999.0

        # Delegate to service layer (handles chain-walk + fallback)
        segments = await asyncio.to_thread(
            lambda: kg.get_transcript_segments(
                effective_id,
                start_time=None if full_transcript else effective_start,
                end_time=None if full_transcript else effective_end,
            )
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

        frame = await asyncio.to_thread(
            lambda: kg.get_nearest_frame(effective_id, timestamp, user_id=user_id)
        )

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


# ---------------------------------------------------------------------------
# Internal helpers — hybrid search with timeout + keyword fallback
# ---------------------------------------------------------------------------


async def _hybrid_search_with_fallback(
    *,
    query: str,
    video_id: str,
    content_type: str = "all",
    limit: int = 5,
    time_range_start: float | None = None,
    time_range_end: float | None = None,
) -> tuple[list[dict[str, Any]], int, float, list[str], str]:
    """Run hybrid search; on timeout/error fall back to keyword Cypher search.

    Returns (results, total_found, search_time_ms, truncated_fields, search_mode).
    """
    from models.graph_models import NodeType

    # --- attempt 1: hybrid search (vector + fulltext + graph + reranking) ---
    try:
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()

        if content_type == "visual":
            node_types = [NodeType.FRAME]
        elif content_type == "audio":
            node_types = [NodeType.AUDIO_SEGMENT]
        else:
            node_types = [
                NodeType.FRAME,
                NodeType.AUDIO_SEGMENT,
                NodeType.ENTITY,
            ]

        search_response = await asyncio.wait_for(
            search_service.hybrid_search(
                query_text=query,
                node_types=node_types,
                video_id=video_id,
                limit=limit * 3,
                expansion_hops=2,
                use_reranking=True,
            ),
            timeout=_HYBRID_SEARCH_TIMEOUT_S,
        )

        results: list[dict[str, Any]] = []
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
                    entity_desc += f" [{', '.join(f'{k}={v}' for k, v in attrs.items())}]"
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

        return (
            results,
            search_response.total_results,
            search_response.vector_search_time_ms,
            truncated_fields,
            "hybrid",
        )

    except TimeoutError:
        logger.warning(
            "search_video: hybrid search timed out after %.0fs, using keyword fallback",
            _HYBRID_SEARCH_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning(
            "search_video: hybrid search failed (%s: %s), using keyword fallback",
            type(exc).__name__,
            exc,
        )

    # --- attempt 2: keyword Cypher fallback (same pattern as working tools) ---
    return await _keyword_search_fallback(
        query=query,
        video_id=video_id,
        content_type=content_type,
        limit=limit,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
    )


async def _keyword_search_fallback(
    *,
    query: str,
    video_id: str,
    content_type: str = "all",
    limit: int = 5,
    time_range_start: float | None = None,
    time_range_end: float | None = None,
) -> tuple[list[dict[str, Any]], int, float, list[str], str]:
    """Keyword-based Cypher search — no embeddings, no Redis, same pattern as working tools."""
    from services.knowledge_graph import get_knowledge_graph_service

    kg = get_knowledge_graph_service()

    include_visual = content_type in ("all", "visual")
    include_audio = content_type in ("all", "audio")

    multimodal = await asyncio.to_thread(
        kg.search_multimodal,
        query_text=query,
        video_id=video_id,
        include_visual=include_visual,
        include_audio=include_audio,
        limit=limit * 2,
    )

    results: list[dict[str, Any]] = []
    truncated_fields: list[str] = []

    for item in multimodal.get("combined_timeline", []):
        ts = item.get("timestamp", 0.0)
        if time_range_start is not None and ts < time_range_start:
            continue
        if time_range_end is not None and ts > time_range_end:
            continue

        raw_content = item.get("content", "")
        item_type = item.get("type", "visual")

        if item_type == "visual":
            desc, was_cut = truncate_with_notice(raw_content, 900)
            if was_cut:
                truncated_fields.append("content")
            results.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "visual",
                    "content": desc,
                }
            )
        elif item_type == "audio":
            text, was_cut = truncate_with_notice(raw_content, 600)
            if was_cut:
                truncated_fields.append("content")
            results.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "audio",
                    "content": text,
                }
            )

        if len(results) >= limit:
            break

    total = multimodal.get("total_visual", 0) + multimodal.get("total_audio", 0)
    return results, total, 0.0, truncated_fields, "keyword_fallback"


async def _entity_graph_fallback(
    entity_name: str,
    media_id: str,
    entity_type: str = "any",
) -> list[dict[str, Any]]:
    """Graph-only entity lookup — sync Cypher via to_thread, no embeddings."""
    from services.knowledge_graph import get_knowledge_graph_service

    kg = get_knowledge_graph_service()

    raw = await asyncio.to_thread(
        kg.find_entity_appearances,
        video_id=media_id,
        entity_name=entity_name,
    )

    occurrences: list[dict[str, Any]] = []
    seen: set[float] = set()

    for section in ("visual", "audio"):
        for item in raw.get(section, []):
            ts = item.get("timestamp", item.get("start_time", 0.0))
            ts_key = round(ts, 1)
            if ts_key in seen:
                continue
            seen.add(ts_key)

            context = item.get("description", item.get("text", ""))
            if len(context) > 500:
                context = context[:497] + "..."

            occ_type = "visible" if section == "visual" else "mentioned"

            occurrences.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "occurrence_type": occ_type,
                    "context": context,
                    "confidence": 0.5,
                }
            )

    # Also check direct entity search
    entity_types_filter = None
    if entity_type != "any":
        from models.graph_models import EntityType

        try:
            entity_types_filter = [EntityType(entity_type)]
        except ValueError:
            pass

    entities = await asyncio.to_thread(
        kg.search_entities,
        query_text=entity_name,
        entity_types=entity_types_filter,
        video_id=media_id,
        limit=10,
    )
    for e in entities:
        ent = e.get("entity", {})
        ts = ent.get("first_seen", 0.0)
        ts_key = round(ts, 1)
        if ts_key in seen:
            continue
        seen.add(ts_key)
        occurrences.append(
            {
                "timestamp": ts,
                "timestamp_formatted": format_timestamp(ts),
                "occurrence_type": "identified",
                "context": f"Entity '{ent.get('name')}' of type {ent.get('entity_type', 'unknown')}",
                "confidence": round(e.get("score", 0.5), 3),
            }
        )

    return occurrences
