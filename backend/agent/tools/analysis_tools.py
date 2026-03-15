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

        # Find all frames and audio mentioning this entity
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                WHERE e.video_id = $media_id
                  AND toLower(e.name) CONTAINS toLower($entity_name)
                OPTIONAL MATCH (e)<-[:CONTAINS]-(f:Frame)
                OPTIONAL MATCH (e)<-[:MENTIONS]-(a:AudioSegment)
                WITH e, collect(DISTINCT {type: 'visual', timestamp: f.timestamp, description: f.description}) as frames,
                     collect(DISTINCT {type: 'audio', timestamp: a.start_time, text: a.text}) as audios
                RETURN e.name as name, e.type as entity_type, frames, audios
                """,
                media_id=media_id,
                entity_name=entity_name,
            )
            entities = list(result)

        timeline = []
        seen_timestamps = set()

        for entity in entities:
            if (
                entity_type != "any"
                and entity.get("entity_type", "").lower() != entity_type.lower()
            ):
                continue

            # Add frame appearances
            for frame in entity.get("frames", []):
                if frame.get("timestamp") is None:
                    continue
                ts = frame["timestamp"]
                ts_key = round(ts, 1)
                if ts_key in seen_timestamps:
                    continue
                seen_timestamps.add(ts_key)

                timeline.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "appearance_type": "visual",
                        "entity_name": entity.get("name"),
                        "context": frame.get("description", "")[:400] if include_context else None,
                    }
                )

            # Add audio mentions
            for audio in entity.get("audios", []):
                if audio.get("timestamp") is None:
                    continue
                ts = audio["timestamp"]
                ts_key = round(ts, 1)
                if ts_key in seen_timestamps:
                    continue
                seen_timestamps.add(ts_key)

                timeline.append(
                    {
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "appearance_type": "spoken",
                        "entity_name": entity.get("name"),
                        "context": audio.get("text", "")[:400] if include_context else None,
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
                        RETURN f.timestamp as timestamp, f.description as description,
                               f.detected_objects as objects, f.frame_url as thumbnail
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
                        "objects_detected": frame.get("objects") or [],
                        "thumbnail_url": frame.get("thumbnail"),
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
