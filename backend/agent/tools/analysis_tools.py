"""
Analysis Tools
==============

LangGraph tools for content analysis: related content exploration,
entity timelines, and moment comparison.
"""

import asyncio
import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp, get_timestamp_from_content
from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice

logger = logging.getLogger(__name__)


@tool
async def get_related_content(
    topic: Annotated[str, "Topic or concept to explore connections for"],
    depth: Annotated[int, "How many relationship hops to explore (1-3)"] = 2,
    target_video_id: Annotated[
        str | None, "Optional video ID to query when multiple videos are in context"
    ] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Explore the knowledge graph to find related entities and connections
    by traversing relationships (1-3 hops from matching nodes).
    Use this to discover how entities and ideas are connected throughout the video.
    For relevance-ranked search, use search_video instead.
    """
    effective_media_id = target_video_id or media_id
    if not effective_media_id:
        return tool_error("no_context", "No video context available.")

    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()

        search_response = await search_service.hybrid_search(
            query_text=topic,
            node_types=[NodeType.ENTITY, NodeType.TOPIC, NodeType.FRAME, NodeType.SCENE],
            video_id=effective_media_id,
            limit=15,
            expansion_hops=min(depth, 3),
            use_reranking=True,
        )

        entities = []
        topics = []
        moments = []
        truncated_fields: list[str] = []

        for r in search_response.results:
            if r.node_type == NodeType.ENTITY:
                desc, was_cut = truncate_with_notice(r.content.get("description", ""), 200)
                if was_cut:
                    truncated_fields.append("description")
                entities.append(
                    {
                        "name": r.content.get("name"),
                        "type": r.content.get("type"),
                        "description": desc,
                        "relevance": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.TOPIC:
                desc, was_cut = truncate_with_notice(r.content.get("description", ""), 200)
                if was_cut:
                    truncated_fields.append("description")
                topics.append(
                    {
                        "name": r.content.get("name"),
                        "description": desc,
                        "relevance": round(r.combined_score, 3),
                    }
                )
            elif r.node_type in [NodeType.FRAME, NodeType.SCENE]:
                ts = get_timestamp_from_content(r.content)
                desc, was_cut = truncate_with_notice(r.content.get("description", ""), 300)
                if was_cut:
                    truncated_fields.append("description")
                moments.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "scene" if r.node_type == NodeType.SCENE else "frame",
                        "description": desc,
                        "relevance": round(r.combined_score, 3),
                    }
                )

        moments.sort(key=lambda x: x["timestamp"])

        return {
            "topic": topic,
            "related_entities": entities[:5],
            "related_topics": topics[:5],
            "related_moments": moments[:8],
            "connections_found": len(search_response.results),
            "exploration_depth": depth,
            "_meta": tool_meta(
                result_count=len(entities) + len(topics) + len(moments),
                total_available=search_response.total_results,
                truncated_fields=list(set(truncated_fields)) if truncated_fields else None,
            ),
        }

    except Exception as e:
        logger.error("get_related_content failed for %s: %s", effective_media_id, e)
        return tool_error("query_error", f"Failed to explore connections: {e}")


async def _resolve_entity_via_hybrid_search(
    entity_name: str,
    entity_type: str,
    media_id: str,
) -> str | None:
    """Resolve a descriptive entity name to a canonical graph entity name.

    Mirrors the ENTITY-restricted hybrid search that ``find_entity`` uses,
    returning the top candidate's canonical name (``r.content["name"]``) so
    callers can retry exact-match graph lookups. Returns ``None`` if no
    candidate matches, the search fails, or the top candidate has no
    usable name field.
    """
    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()
        # NOTE: wait_for releases the awaiting task on timeout but cannot cancel
        # the underlying asyncio.to_thread sync work inside hybrid_search. The
        # search service has its own internal budget controls; this guard only
        # bounds the latency this fallback adds to a single get_entity_timeline
        # call. A deeper fix would propagate a timeout_s budget into the search
        # pipeline itself.
        search_response = await asyncio.wait_for(
            search_service.hybrid_search(
                query_text=entity_name,
                node_types=[NodeType.ENTITY],
                video_id=media_id,
                limit=5,
                expansion_hops=1,
                use_reranking=True,
            ),
            timeout=10.0,
        )
    except Exception as exc:
        logger.debug(
            "_resolve_entity_via_hybrid_search: failed for '%s' (%s)",
            entity_name[:50],
            exc,
        )
        return None

    requested_type = (entity_type or "any").lower()
    for r in search_response.results:
        if getattr(r, "node_type", None) != NodeType.ENTITY:
            continue
        candidate_type = (r.content.get("type") or "").lower()
        if requested_type != "any" and candidate_type and candidate_type != requested_type:
            continue
        name = r.content.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


@tool
async def get_entity_timeline(
    entity_name: Annotated[str, "Name of the entity to track"],
    entity_type: Annotated[
        str, "Type: 'person', 'object', 'concept', 'location', or 'any'"
    ] = "any",
    include_context: Annotated[bool, "Include surrounding context for each appearance"] = True,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
) -> dict[str, Any]:
    """
    Build a complete chronological timeline of all appearances of an entity
    throughout the video. Returns ordered moments with rich detail for each
    appearance. Useful for tracking how a person, object, or concept evolves over time.
    For a quick list of where an entity appears, use find_entity instead.

    Tip: pass canonical entity names from the graph (use find_entity first for
    descriptive phrases like "middle-aged presenter with gray hair"). When this
    tool receives a non-canonical name and finds no direct match, it will
    transparently fuzzy-resolve the name and retry; the substituted name is
    reported in the response as ``resolved_entity_name``.
    """
    if not media_id:
        return tool_error("no_context", "No video context available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        logger.info(
            "get_entity_timeline: querying | entity=%s type=%s media_id=%s",
            entity_name[:50],
            entity_type,
            media_id,
        )

        appearances = await asyncio.to_thread(
            lambda: kg.find_entity_appearances(media_id, entity_name, user_id=user_id)
        )
        visual_records = appearances.get("visual", [])
        audio_records = appearances.get("audio", [])

        resolved_entity_name: str | None = None
        resolution_method: str | None = None

        if not visual_records and not audio_records:
            logger.info(
                "get_entity_timeline: 0 exact matches for '%s' — attempting "
                "fuzzy entity resolution via hybrid search",
                entity_name[:50],
            )
            resolved = await _resolve_entity_via_hybrid_search(
                entity_name=entity_name,
                entity_type=entity_type,
                media_id=media_id,
            )
            if resolved and resolved != entity_name:
                resolved_entity_name = resolved
                resolution_method = "hybrid_search_fuzzy"
                appearances = await asyncio.to_thread(
                    lambda: kg.find_entity_appearances(media_id, resolved, user_id=user_id)
                )
                visual_records = appearances.get("visual", [])
                audio_records = appearances.get("audio", [])
                logger.info(
                    "get_entity_timeline: fuzzy fallback | original='%s' "
                    "resolved='%s' visual=%d audio=%d",
                    entity_name[:50],
                    resolved[:50],
                    len(visual_records),
                    len(audio_records),
                )
            else:
                logger.warning(
                    "get_entity_timeline: 0 results for '%s' (no fuzzy match "
                    "found either). Entity extraction may not have run or the "
                    "name may not exist in the graph.",
                    entity_name[:50],
                )

        timeline = []
        seen_timestamps: set[float] = set()

        for record in visual_records:
            if (
                entity_type != "any"
                and (record.get("entity_type") or "").lower() != entity_type.lower()
            ):
                continue

            ts = record.get("timestamp")
            if ts is None:
                continue
            ts_key = round(ts, 1)
            if ts_key in seen_timestamps:
                continue
            seen_timestamps.add(ts_key)

            ctx = None
            if include_context:
                ctx, _ = truncate_with_notice(record.get("description", ""), 400)

            timeline.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "visual",
                    "entity_name": record.get("name"),
                    "context": ctx,
                }
            )

        # Use the resolved canonical name for entries when fuzzy resolution
        # succeeded so visual and spoken entries refer to the same entity.
        canonical_entity_name = resolved_entity_name or entity_name

        for record in audio_records:
            ts = record.get("timestamp")
            if ts is None:
                continue
            ts_key = round(ts, 1)
            if ts_key in seen_timestamps:
                continue
            seen_timestamps.add(ts_key)

            ctx = None
            if include_context:
                ctx, _ = truncate_with_notice(record.get("text", ""), 400)

            timeline.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "spoken",
                    "entity_name": canonical_entity_name,
                    "context": ctx,
                }
            )

        timeline.sort(key=lambda x: x["timestamp"])

        visual_count = sum(1 for t in timeline if t["appearance_type"] == "visual")
        spoken_count = sum(1 for t in timeline if t["appearance_type"] == "spoken")

        shown = timeline[:30]
        payload: dict[str, Any] = {
            "entity": canonical_entity_name,
            "entity_type": entity_type,
            "total_appearances": len(timeline),
            "visual_appearances": visual_count,
            "spoken_mentions": spoken_count,
            "timeline": shown,
            "first_appearance": timeline[0]["timestamp_formatted"] if timeline else None,
            "last_appearance": timeline[-1]["timestamp_formatted"] if timeline else None,
            "_meta": tool_meta(
                result_count=len(shown),
                total_available=len(timeline),
            ),
        }
        if resolved_entity_name:
            payload["resolved_entity_name"] = resolved_entity_name
            payload["original_entity_name"] = entity_name
            payload["resolution_method"] = resolution_method
        return payload

    except Exception as e:
        logger.error("get_entity_timeline failed for %s: %s", media_id, e)
        return tool_error("query_error", f"Failed to create entity timeline: {e}")


@tool
async def compare_moments(
    timestamps: Annotated[list[float], "List of timestamps (in seconds) to compare"],
    comparison_aspect: Annotated[str, "What to compare: 'visual', 'audio', 'all'"] = "all",
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Compare multiple moments in the video side by side.
    Useful for understanding progression, changes, or differences between scenes.
    Returns frame descriptions and surrounding detail for each timestamp to enable comparison.
    Provide 2-5 timestamps in seconds.
    """
    if not media_id:
        return tool_error("no_context", "No video context available.")

    if len(timestamps) < 2:
        return tool_error("invalid_input", "Need at least 2 timestamps to compare.")

    if len(timestamps) > 5:
        return tool_error("invalid_input", "Maximum 5 timestamps can be compared at once.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()

        # Batched retrieval: 2 queries total instead of 2 per timestamp
        moments_data = await asyncio.to_thread(
            lambda: kg.get_moments_context(media_id, timestamps, window=5.0)
        )

        comparison = []
        truncated_fields: list[str] = []
        for moment in moments_data:
            ts = moment["timestamp"]
            moment_entry: dict[str, Any] = {
                "timestamp": ts,
                "timestamp_formatted": format_timestamp(ts),
            }

            if comparison_aspect in ["visual", "all"] and moment.get("visual"):
                frame = moment["visual"]
                desc, was_cut = truncate_with_notice(frame.get("description") or "", 500)
                if was_cut:
                    truncated_fields.append("description")
                moment_entry["visual"] = {
                    "actual_timestamp": frame.get("timestamp"),
                    "description": desc,
                }

            if comparison_aspect in ["audio", "all"] and moment.get("audio"):
                audio_segs = moment["audio"]
                texts = [seg.get("text", "") for seg in audio_segs]
                speakers = list({seg.get("speaker") for seg in audio_segs if seg.get("speaker")})
                transcript, was_cut = truncate_with_notice(" ".join(texts), 400)
                if was_cut:
                    truncated_fields.append("transcript")
                moment_entry["audio"] = {
                    "transcript": transcript,
                    "speakers": speakers,
                }

            comparison.append(moment_entry)

        return {
            "timestamps_compared": len(timestamps),
            "comparison_aspect": comparison_aspect,
            "moments": comparison,
            "summary": (
                f"Compared {len(timestamps)} moments from "
                f"{format_timestamp(min(timestamps))} to {format_timestamp(max(timestamps))}"
            ),
            "_meta": tool_meta(
                result_count=len(comparison),
                truncated_fields=list(set(truncated_fields)) if truncated_fields else None,
            ),
        }

    except Exception as e:
        logger.error("compare_moments failed for %s: %s", media_id, e)
        return tool_error("query_error", f"Failed to compare moments: {e}")
