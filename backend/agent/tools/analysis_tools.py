"""
Analysis Tools
==============

LangGraph tools for content analysis: related content exploration,
entity timelines, and moment comparison.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp, get_timestamp_from_content

logger = logging.getLogger(__name__)


@tool
async def get_related_content(
    topic: Annotated[str, "Topic or concept to explore connections for"],
    depth: Annotated[int, "How many relationship hops to explore (1-3)"] = 2,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Explore the knowledge graph to find related content, entities, and connections.
    Use this to discover how topics/entities are connected throughout the video.
    """
    if not media_id:
        return {"error": "No video context available.", "related": []}

    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        # Search with graph expansion
        search_response = await search_service.hybrid_search(
            query_text=topic,
            node_types=[NodeType.ENTITY, NodeType.TOPIC, NodeType.FRAME, NodeType.SCENE],
            video_id=media_id,
            limit=15,
            expansion_hops=min(depth, 3),
            use_reranking=True,
        )

        # Group by type
        entities = []
        topics = []
        moments = []

        for r in search_response.results:
            if r.node_type == NodeType.ENTITY:
                entities.append(
                    {
                        "name": r.content.get("name"),
                        "type": r.content.get("type"),
                        "description": r.content.get("description", "")[:200],
                        "relevance": round(r.combined_score, 3),
                    }
                )
            elif r.node_type == NodeType.TOPIC:
                topics.append(
                    {
                        "name": r.content.get("name"),
                        "description": r.content.get("description", "")[:200],
                        "relevance": round(r.combined_score, 3),
                    }
                )
            elif r.node_type in [NodeType.FRAME, NodeType.SCENE]:
                ts = get_timestamp_from_content(r.content)
                moments.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "scene" if r.node_type == NodeType.SCENE else "frame",
                        "description": r.content.get("description", "")[:300],
                        "relevance": round(r.combined_score, 3),
                    }
                )

        # Sort moments by timestamp
        moments.sort(key=lambda x: x["timestamp"])

        return {
            "topic": topic,
            "related_entities": entities[:5],
            "related_topics": topics[:5],
            "related_moments": moments[:8],
            "connections_found": len(search_response.results),
            "exploration_depth": depth,
        }

    except Exception as e:
        return {"error": f"Failed to explore connections: {str(e)}", "related": []}


@tool
async def get_entity_timeline(
    entity_name: Annotated[str, "Name of the entity to track"],
    entity_type: Annotated[
        str, "Type: 'person', 'object', 'concept', 'location', or 'any'"
    ] = "any",
    include_context: Annotated[bool, "Include surrounding context for each appearance"] = True,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Create a complete timeline of all appearances of an entity throughout the video.
    Returns chronologically ordered moments with rich context.
    Useful for tracking how a person, object, or topic appears over time.
    """
    if not media_id:
        return {"error": "No video context available.", "timeline": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        # Find visual appearances via entity-frame links
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (e:Entity)<-[:CONTAINS]-(f:Frame)
                WHERE e.video_id = $media_id
                  AND toLower(e.name) CONTAINS toLower($entity_name)
                RETURN e.name as name, e.entity_type as entity_type,
                       f.timestamp as timestamp, f.description as description
                ORDER BY f.timestamp
                """,
                media_id=media_id,
                entity_name=entity_name,
            )
            visual_records = list(result)

        # Find audio mentions via text search
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $media_id
                  AND toLower(a.text) CONTAINS toLower($entity_name)
                RETURN a.start_time as timestamp, a.text as text
                ORDER BY a.start_time
                """,
                media_id=media_id,
                entity_name=entity_name,
            )
            audio_records = list(result)

        timeline = []
        seen_timestamps = set()

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

            timeline.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "visual",
                    "entity_name": record.get("name"),
                    "context": record.get("description", "")[:400] if include_context else None,
                }
            )

        for record in audio_records:
            ts = record.get("timestamp")
            if ts is None:
                continue
            ts_key = round(ts, 1)
            if ts_key in seen_timestamps:
                continue
            seen_timestamps.add(ts_key)

            timeline.append(
                {
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "spoken",
                    "entity_name": entity_name,
                    "context": record.get("text", "")[:400] if include_context else None,
                }
            )

        # Sort by timestamp
        timeline.sort(key=lambda x: x["timestamp"])

        # Calculate statistics
        visual_count = sum(1 for t in timeline if t["appearance_type"] == "visual")
        spoken_count = sum(1 for t in timeline if t["appearance_type"] == "spoken")

        return {
            "entity": entity_name,
            "entity_type": entity_type,
            "total_appearances": len(timeline),
            "visual_appearances": visual_count,
            "spoken_mentions": spoken_count,
            "timeline": timeline[:30],  # Limit for context window
            "first_appearance": timeline[0]["timestamp_formatted"] if timeline else None,
            "last_appearance": timeline[-1]["timestamp_formatted"] if timeline else None,
        }

    except Exception as e:
        return {"error": f"Failed to create entity timeline: {str(e)}", "timeline": []}


@tool
async def compare_moments(
    timestamps: Annotated[list[float], "List of timestamps (in seconds) to compare"],
    comparison_aspect: Annotated[str, "What to compare: 'visual', 'audio', 'all'"] = "all",
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Compare multiple moments in the video side by side.
    Useful for understanding progression, changes, or differences between scenes.
    Returns detailed context for each moment to enable comparison.
    """
    if not media_id:
        return {"error": "No video context available.", "comparison": []}

    if len(timestamps) < 2:
        return {"error": "Need at least 2 timestamps to compare.", "comparison": []}

    if len(timestamps) > 5:
        return {"error": "Maximum 5 timestamps can be compared at once.", "comparison": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        comparison = []

        for ts in sorted(timestamps):
            moment_data = {
                "timestamp": ts,
                "timestamp_formatted": format_timestamp(ts),
            }

            # Get visual content
            if comparison_aspect in ["visual", "all"]:
                with kg.get_session() as session:
                    result = session.run(
                        """
                        MATCH (f:Frame)
                        WHERE f.video_id = $media_id
                        RETURN f.timestamp as timestamp, f.description as description
                        ORDER BY abs(f.timestamp - $timestamp)
                        LIMIT 1
                        """,
                        media_id=media_id,
                        timestamp=ts,
                    )
                    frame = result.single()

                if frame:
                    moment_data["visual"] = {
                        "actual_timestamp": frame.get("timestamp"),
                        "description": frame.get("description", "")[:500],
                    }

            # Get audio content
            if comparison_aspect in ["audio", "all"]:
                with kg.get_session() as session:
                    result = session.run(
                        """
                        MATCH (a:AudioSegment)
                        WHERE a.video_id = $media_id
                          AND a.start_time >= $start AND a.start_time <= $end
                        RETURN a.text as text, a.speaker_label as speaker
                        ORDER BY a.start_time
                        """,
                        media_id=media_id,
                        start=ts - 5,
                        end=ts + 5,
                    )
                    audio_segments = list(result)

                if audio_segments:
                    texts = [seg.get("text", "") for seg in audio_segments]
                    speakers = list(
                        {seg.get("speaker") for seg in audio_segments if seg.get("speaker")}
                    )
                    moment_data["audio"] = {
                        "transcript": " ".join(texts)[:400],
                        "speakers": speakers,
                    }

            comparison.append(moment_data)

        return {
            "timestamps_compared": len(timestamps),
            "comparison_aspect": comparison_aspect,
            "moments": comparison,
            "summary": f"Compared {len(timestamps)} moments from {format_timestamp(min(timestamps))} to {format_timestamp(max(timestamps))}",
        }

    except Exception as e:
        return {"error": f"Failed to compare moments: {str(e)}", "comparison": []}
