"""
LangGraph Tools
===============

Tools for the video agent using LangGraph @tool decorator.
Uses InjectedState for proper context injection from graph state.
"""

from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp, get_timestamp_from_content

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
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
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
            ts = get_timestamp_from_content(r.content)

            if time_range_start is not None and ts < time_range_start:
                continue
            if time_range_end is not None and ts > time_range_end:
                continue

            if r.node_type == NodeType.FRAME:
                results.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "visual",
                    "content": r.content.get("description", "")[:600],
                    "score": round(r.combined_score, 3),
                })
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                results.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "audio",
                    "content": r.content.get("text", "")[:600],
                    "score": round(r.combined_score, 3),
                })
            elif r.node_type == NodeType.ENTITY:
                results.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
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
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
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
                  AND a.timestamp >= $start_time
                  AND a.timestamp <= $end_time
                RETURN a.timestamp as timestamp, a.text as text, 
                       a.speaker as speaker, a.confidence as confidence
                ORDER BY a.timestamp
                """,
                media_id=media_id,
                start_time=start_time,
                end_time=end_time
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
                timestamp=timestamp
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
                media_id=media_id
            )
            scenes = list(result)

        if not scenes:
            # Try to get video topics as alternative
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (v:Video)
                    WHERE v.video_id = $media_id OR v.id = $media_id
                    RETURN v.topics as topics, v.summary as summary
                    """,
                    media_id=media_id
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
                RETURN v.summary as summary, v.title as title, v.topics as topics,
                       v.duration_seconds as duration
                """,
                media_id=media_id
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

        # Get frames in the window
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
                end_time=end_time
            )
            frames = list(result)

        # Get audio segments in the window
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $media_id
                  AND a.timestamp >= $start_time
                  AND a.timestamp <= $end_time
                RETURN a.timestamp as timestamp, a.text as text
                ORDER BY a.timestamp
                """,
                media_id=media_id,
                start_time=start_time,
                end_time=end_time
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
                timestamp=timestamp
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
            "current_scene": {
                "type": scene.get("scene_type") if scene else None,
                "description": scene.get("description") if scene else None,
                "time_range": f"{format_timestamp(scene.get('start_time', 0))} - {format_timestamp(scene.get('end_time', 0))}" if scene else None,
            } if scene else None,
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
                    for a in audio_segments if timestamp - 10 <= a["timestamp"] <= timestamp + 10
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
        from api.dependencies import get_graph_search_service
        from models.graph_models import NodeType

        search_service = get_graph_search_service()

        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        # Search with graph expansion
        search_response = search_service.hybrid_search(
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
                entities.append({
                    "name": r.content.get("name"),
                    "type": r.content.get("type"),
                    "description": r.content.get("description", "")[:200],
                    "relevance": round(r.combined_score, 3),
                })
            elif r.node_type == NodeType.TOPIC:
                topics.append({
                    "name": r.content.get("name"),
                    "description": r.content.get("description", "")[:200],
                    "relevance": round(r.combined_score, 3),
                })
            elif r.node_type in [NodeType.FRAME, NodeType.SCENE]:
                ts = get_timestamp_from_content(r.content)
                moments.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "type": "scene" if r.node_type == NodeType.SCENE else "frame",
                    "description": r.content.get("description", "")[:300],
                    "relevance": round(r.combined_score, 3),
                })

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
    entity_type: Annotated[str, "Type: 'person', 'object', 'concept', 'location', or 'any'"] = "any",
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
                     collect(DISTINCT {type: 'audio', timestamp: a.timestamp, text: a.text}) as audios
                RETURN e.name as name, e.type as entity_type, frames, audios
                """,
                media_id=media_id,
                entity_name=entity_name
            )
            entities = list(result)

        timeline = []
        seen_timestamps = set()

        for entity in entities:
            if entity_type != "any" and entity.get("entity_type", "").lower() != entity_type.lower():
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

                timeline.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "visual",
                    "entity_name": entity.get("name"),
                    "context": frame.get("description", "")[:400] if include_context else None,
                })

            # Add audio mentions
            for audio in entity.get("audios", []):
                if audio.get("timestamp") is None:
                    continue
                ts = audio["timestamp"]
                ts_key = round(ts, 1)
                if ts_key in seen_timestamps:
                    continue
                seen_timestamps.add(ts_key)

                timeline.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "appearance_type": "spoken",
                    "entity_name": entity.get("name"),
                    "context": audio.get("text", "")[:400] if include_context else None,
                })

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
                        timestamp=ts
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
                          AND a.timestamp >= $start AND a.timestamp <= $end
                        RETURN a.text as text, a.speaker as speaker
                        ORDER BY a.timestamp
                        """,
                        media_id=media_id,
                        start=ts - 5,
                        end=ts + 5
                    )
                    audio_segments = list(result)

                if audio_segments:
                    texts = [seg.get("text", "") for seg in audio_segments]
                    speakers = list(set(seg.get("speaker") for seg in audio_segments if seg.get("speaker")))
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


def _time_range_overlaps(start: float, end: float, used_ranges: list[tuple[float, float]]) -> bool:
    """Check if a time range overlaps with any existing used ranges."""
    for used_start, used_end in used_ranges:
        if start < used_end and end > used_start:
            return True
    return False


def _find_frame_highlights(
    kg,
    media_id: str,
    segment_duration: float,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 1: Find frames with rich descriptions distributed across video.
    Divides video into segments and picks the best frame from each segment.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    # Get candidate frames with rich descriptions
    with kg.get_session() as session:
        result = session.run(
            """
            MATCH (f:Frame)
            WHERE f.video_id = $media_id AND f.description IS NOT NULL
              AND size(f.description) > 80
            RETURN f.timestamp as timestamp, f.description as description,
                   size(f.description) as desc_length
            ORDER BY size(f.description) DESC
            LIMIT 100
            """,
            media_id=media_id
        )
        candidate_frames = list(result)

    # Distribute frames across video by picking best from different time segments
    segment_best = {}
    for frame in candidate_frames:
        ts = frame.get("timestamp", 0)
        segment_idx = int(ts / segment_duration) if segment_duration > 0 else 0

        # Keep best (longest description) per segment
        if segment_idx not in segment_best or frame.get("desc_length", 0) > segment_best[segment_idx].get("desc_length", 0):
            segment_best[segment_idx] = frame

    # Sort segments by quality and pick top ones, distributed across video
    sorted_segments = sorted(segment_best.items(), key=lambda x: x[1].get("desc_length", 0), reverse=True)

    # Get video duration from first frame if available
    video_duration = 0
    if candidate_frames:
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (v:Video)
                WHERE v.id = $media_id OR v.video_id = $media_id
                RETURN v.duration as duration
                LIMIT 1
                """,
                media_id=media_id
            )
            video = result.single()
            video_duration = video.get("duration", 0) if video else 0

    for segment_idx, frame in sorted_segments:
        if len(highlights) >= max_clips:
            break

        ts = frame.get("timestamp", 0)
        # Create clip around this timestamp
        half_duration = min_duration / 2
        start = max(0, ts - half_duration)
        end = min(video_duration if video_duration > 0 else ts + half_duration, ts + half_duration)

        # Ensure minimum duration
        if end - start < min_duration:
            end = start + min_duration

        if _time_range_overlaps(start, end, used_ranges):
            continue

        desc = frame.get("description", "") or ""
        highlights.append({
            "start_time": start,
            "end_time": end,
            "start_formatted": format_timestamp(start),
            "end_formatted": format_timestamp(end),
            "duration": round(end - start, 1),
            "title": "Content Highlight",
            "description": desc[:200],
            "highlight_reason": "Rich visual content (distributed)",
            "suggested_for": ["social_clip", "preview"],
        })
        used_ranges.append((start, end))

    return highlights


def _find_scene_highlights(
    kg,
    media_id: str,
    segment_duration: float,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 2: Find scenes with visual variety distributed across video.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    with kg.get_session() as session:
        # Get scenes from different parts of the video
        result = session.run(
            """
            MATCH (s:Scene)
            WHERE s.video_id = $media_id
            WITH s, (s.start_time / $segment_size) as segment
            WITH segment, collect(s) as scenes
            UNWIND scenes[0..1] as scene
            RETURN scene.start_time as start, scene.end_time as end
            ORDER BY segment
            """,
            media_id=media_id,
            segment_size=segment_duration * 2
        )
        distributed_scenes = list(result)

    for scene in distributed_scenes:
        if len(highlights) >= max_clips:
            break

        start = scene.get("start", 0)
        end = scene.get("end", 0)
        duration = end - start if end else min_duration

        if duration < min_duration or duration > max_duration:
            continue
        if _time_range_overlaps(start, end, used_ranges):
            continue

        # Get description from a frame within this scene
        scene_desc = ""
        with kg.get_session() as session:
            frame_result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $media_id
                  AND f.timestamp >= $start AND f.timestamp <= $end
                  AND f.description IS NOT NULL
                RETURN f.description as description
                ORDER BY size(f.description) DESC
                LIMIT 1
                """,
                media_id=media_id, start=start, end=end
            )
            frame_rec = frame_result.single()
            if frame_rec:
                scene_desc = frame_rec.get("description", "") or ""

        highlights.append({
            "start_time": start,
            "end_time": end,
            "start_formatted": format_timestamp(start),
            "end_formatted": format_timestamp(end),
            "duration": round(duration, 1),
            "title": "Visual Highlight",
            "description": scene_desc[:200] if scene_desc else f"Scene from {format_timestamp(start)} to {format_timestamp(end)}",
            "highlight_reason": "Key visual moment",
            "suggested_for": ["social_clip", "preview"],
        })
        used_ranges.append((start, end))

    return highlights


def _find_entity_highlights(
    kg,
    media_id: str,
    max_clips: int,
    min_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 3: Find frames with multiple entities (key moments).
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    with kg.get_session() as session:
        result = session.run(
            """
            MATCH (e:Entity)-[:APPEARS_IN]->(f:Frame)
            WHERE f.video_id = $media_id
            WITH f, count(e) as entity_count
            WHERE entity_count > 2
            RETURN f.timestamp as timestamp, f.description as description, entity_count
            ORDER BY entity_count DESC
            LIMIT 20
            """,
            media_id=media_id
        )
        entity_rich_frames = list(result)

    for frame in entity_rich_frames:
        if len(highlights) >= max_clips:
            break

        ts = frame.get("timestamp", 0)
        start = max(0, ts - min_duration / 2)
        end = ts + min_duration / 2

        if _time_range_overlaps(start, end, used_ranges):
            continue

        desc = frame.get("description", "") or ""
        highlights.append({
            "start_time": start,
            "end_time": end,
            "start_formatted": format_timestamp(start),
            "end_formatted": format_timestamp(end),
            "duration": round(end - start, 1),
            "title": "Key Moment",
            "description": desc[:200],
            "highlight_reason": f"Multiple key entities ({frame.get('entity_count', 0)} detected)",
            "suggested_for": ["social_clip", "highlight_reel"],
        })
        used_ranges.append((start, end))

    return highlights


def _find_fallback_highlights(
    kg,
    media_id: str,
    video_duration: float,
    max_clips: int,
    min_duration: float,
    used_ranges: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    Strategy 4: Fallback - evenly spaced key moments from video.
    Returns highlights and updates used_ranges in place.
    """
    highlights = []

    if video_duration <= 0:
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (v:Video)
                WHERE v.id = $media_id OR v.video_id = $media_id
                RETURN v.duration as duration
                LIMIT 1
                """,
                media_id=media_id
            )
            video = result.single()
            video_duration = video.get("duration", 0) if video else 0

    if video_duration > 0:
        # Sample evenly from first 3rd, middle, and last 3rd
        sample_points = [
            video_duration * 0.1,  # 10% mark
            video_duration * 0.5,  # Middle
            video_duration * 0.85, # Near end
        ]

        for ts in sample_points:
            if len(highlights) >= max_clips:
                break

            start = max(0, ts - min_duration / 2)
            end = min(video_duration, ts + min_duration / 2)

            if _time_range_overlaps(start, end, used_ranges):
                continue

            highlights.append({
                "start_time": start,
                "end_time": end,
                "start_formatted": format_timestamp(start),
                "end_formatted": format_timestamp(end),
                "duration": round(end - start, 1),
                "title": f"Sample at {int(ts/video_duration*100)}%",
                "description": f"Key moment from {format_timestamp(start)} to {format_timestamp(end)}",
                "highlight_reason": "Representative sample",
                "suggested_for": ["preview"],
            })
            used_ranges.append((start, end))

    return highlights


@tool
async def find_highlights(
    criteria: Annotated[str, "What makes a moment a highlight: 'engagement', 'action', 'key_topics', 'all'"] = "all",
    max_clips: Annotated[int, "Maximum number of highlight clips to suggest"] = 5,
    min_duration: Annotated[float, "Minimum clip duration in seconds"] = 10.0,
    max_duration: Annotated[float, "Maximum clip duration in seconds"] = 60.0,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Identify highlight moments suitable for clips or social media.
    Returns exportable time ranges with descriptions of why they're highlights.
    """
    if not media_id:
        return {"error": "No video context available.", "highlights": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        highlights = []
        used_ranges = []

        # Get video duration for distributing highlights
        video_duration = 0
        with kg.get_session() as session:
            result = session.run(
                """
                MATCH (v:Video)
                WHERE v.id = $media_id OR v.video_id = $media_id
                RETURN v.duration as duration
                LIMIT 1
                """,
                media_id=media_id
            )
            video = result.single()
            video_duration = video.get("duration", 0) if video else 0

        # If no video node, estimate from max scene end time
        if not video_duration:
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (s:Scene)
                    WHERE s.video_id = $media_id
                    RETURN max(s.end_time) as max_end
                    """,
                    media_id=media_id
                )
                rec = result.single()
                video_duration = rec.get("max_end", 0) if rec else 0

        # Calculate segment duration for strategies
        num_segments = max(max_clips * 2, 10)
        segment_duration = video_duration / num_segments if video_duration > 0 else 300

        # Strategy 1: Frames with rich descriptions distributed across video
        frame_highlights = _find_frame_highlights(
            kg, media_id, segment_duration, max_clips, min_duration, max_duration, used_ranges
        )
        highlights.extend(frame_highlights)

        # Strategy 2: Scenes with visual variety
        if len(highlights) < max_clips:
            scene_highlights = _find_scene_highlights(
                kg, media_id, segment_duration, max_clips - len(highlights),
                min_duration, max_duration, used_ranges
            )
            highlights.extend(scene_highlights)

        # Strategy 3: Frames with multiple entities
        if len(highlights) < max_clips:
            entity_highlights = _find_entity_highlights(
                kg, media_id, max_clips - len(highlights), min_duration, used_ranges
            )
            highlights.extend(entity_highlights)

        # Strategy 4: Fallback - evenly spaced key moments
        if len(highlights) < 3:
            fallback_highlights = _find_fallback_highlights(
                kg, media_id, video_duration, max_clips - len(highlights),
                min_duration, used_ranges
            )
            highlights.extend(fallback_highlights)

        # Sort by start time
        highlights.sort(key=lambda x: x["start_time"])

        return {
            "criteria": criteria,
            "total_highlights": len(highlights),
            "highlights": highlights,
            "exportable": True,
            "message": f"Found {len(highlights)} potential highlight clips for this video.",
        }

    except Exception as e:
        return {"error": f"Failed to find highlights: {str(e)}", "highlights": []}


@tool
async def search_across_videos(
    query: Annotated[str, "What to search for across all videos"],
    limit_per_video: Annotated[int, "Maximum results per video"] = 3,
    max_videos: Annotated[int, "Maximum number of videos to search"] = 5,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
) -> dict[str, Any]:
    """
    Search for content across all of the user's processed videos.
    Useful for finding where a topic appears across different videos.
    Returns results grouped by video.
    """
    if not user_id:
        return {"error": "User context not available.", "results": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        # Get all videos for user (need to join with PostgreSQL or have user_id in Neo4j)
        # For now, search across all videos in the graph
        with kg.get_session() as session:
            result = session.run(
                """
                CALL db.index.fulltext.queryNodes('frame_search', $query) YIELD node, score
                WITH node as f, score
                MATCH (v:Video)-[:HAS_FRAME]->(f)
                RETURN v.video_id as video_id, v.title as video_title,
                       collect({
                           timestamp: f.timestamp,
                           description: f.description,
                           score: score
                       })[0..$limit] as matches
                ORDER BY max(score) DESC
                LIMIT $max_videos
                """,
                query=query,
                limit=limit_per_video,
                max_videos=max_videos
            )
            video_results = list(result)

        if not video_results:
            # Try audio search as fallback
            with kg.get_session() as session:
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes('audio_search', $query) YIELD node, score
                    WITH node as a, score
                    MATCH (v:Video)-[:HAS_AUDIO]->(a)
                    RETURN v.video_id as video_id, v.title as video_title,
                           collect({
                               timestamp: a.timestamp,
                               text: a.text,
                               score: score
                           })[0..$limit] as matches
                    ORDER BY max(score) DESC
                    LIMIT $max_videos
                    """,
                    query=query,
                    limit=limit_per_video,
                    max_videos=max_videos
                )
                video_results = list(result)

        results_by_video = []
        for vr in video_results:
            matches = []
            for m in vr.get("matches", []):
                matches.append({
                    "timestamp": m.get("timestamp", 0),
                    "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                    "content": (m.get("description") or m.get("text", ""))[:200],
                    "score": round(m.get("score", 0), 3),
                })
            
            results_by_video.append({
                "video_id": vr.get("video_id"),
                "video_title": vr.get("video_title") or "Untitled",
                "matches": matches,
                "match_count": len(matches),
            })

        return {
            "query": query,
            "videos_searched": len(results_by_video),
            "results_by_video": results_by_video,
            "total_matches": sum(r["match_count"] for r in results_by_video),
        }

    except Exception as e:
        return {"error": f"Cross-video search failed: {str(e)}", "results": []}


# =============================================================================
# Tool Collections
# =============================================================================

SEARCH_TOOLS = [
    search_video,
    find_entity,
    get_transcript,
    describe_scene,
    get_scene_context,
    list_chapters,
    get_video_info,
    get_summary,
    get_related_content,
    get_entity_timeline,
    compare_moments,
    find_highlights,
    search_across_videos,
]

# Note: Editor tools will be added separately for the EditorAgent graph
