"""
Multi-Video Tools
=================

LangGraph tools for cross-video search, comparison, and analysis.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


@tool
async def search_across_videos(
    query: Annotated[str, "What to search for across all videos"],
    limit_per_video: Annotated[int, "Maximum results per video"] = 3,
    max_videos: Annotated[int, "Maximum number of videos to search"] = 5,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
    media_ids: Annotated[list[str] | None, InjectedState("media_ids")] = None,
) -> dict[str, Any]:
    """
    Search for content across multiple videos.
    When media_ids are provided (multi-video mode), searches only those videos.
    Otherwise, searches all of the user's processed videos.
    Returns results grouped by video.
    """
    if not user_id and not media_ids:
        return {"error": "User context not available.", "results": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        # Build query based on whether we have specific media_ids
        if media_ids:
            # Scoped search across specific videos
            with kg.get_session() as session:
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes('frame_search', $query) YIELD node, score
                    WITH node as f, score
                    WHERE f.video_id IN $media_ids
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
                    media_ids=media_ids,
                    limit=limit_per_video,
                    max_videos=max_videos,
                )
                video_results = list(result)

            if not video_results:
                # Try audio search as fallback
                with kg.get_session() as session:
                    result = session.run(
                        """
                        CALL db.index.fulltext.queryNodes('audio_search', $query) YIELD node, score
                        WITH node as a, score
                        WHERE a.video_id IN $media_ids
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
                        media_ids=media_ids,
                        limit=limit_per_video,
                        max_videos=max_videos,
                    )
                    video_results = list(result)
        else:
            # Search across all videos (original behavior)
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
                    max_videos=max_videos,
                )
                video_results = list(result)

            if not video_results:
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
                        max_videos=max_videos,
                    )
                    video_results = list(result)

        results_by_video = []
        for vr in video_results:
            matches = []
            for m in vr.get("matches", []):
                matches.append(
                    {
                        "timestamp": m.get("timestamp", 0),
                        "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                        "content": (m.get("description") or m.get("text", ""))[:200],
                        "score": round(m.get("score", 0), 3),
                    }
                )

            results_by_video.append(
                {
                    "video_id": vr.get("video_id"),
                    "video_title": vr.get("video_title") or "Untitled",
                    "matches": matches,
                    "match_count": len(matches),
                }
            )

        return {
            "query": query,
            "videos_searched": len(results_by_video),
            "scoped_to_selection": media_ids is not None,
            "results_by_video": results_by_video,
            "total_matches": sum(r["match_count"] for r in results_by_video),
        }

    except Exception as e:
        return {"error": f"Cross-video search failed: {str(e)}", "results": []}


@tool
async def compare_videos(
    query: Annotated[
        str,
        "What aspect to compare across the selected videos "
        "(e.g., 'revenue growth', 'main topics', 'speakers')",
    ],
    media_ids: Annotated[list[str] | None, InjectedState("media_ids")] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Compare content across multiple selected videos.
    Finds how each video covers a given topic and highlights similarities and differences.
    Requires multi-video mode (2+ videos selected).
    """
    # Build effective list
    effective_ids: list[str] = []
    if media_ids:
        effective_ids = list(media_ids)
    elif media_id:
        effective_ids = [media_id]

    if len(effective_ids) < 2:
        return {
            "error": "Compare requires at least 2 videos selected. Currently only "
            f"{len(effective_ids)} video(s) in context.",
            "comparison": [],
        }

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        comparison = []
        for vid in effective_ids[:10]:
            # Get video metadata
            with kg.get_session() as session:
                result = session.run(
                    """
                    MATCH (v:Video)
                    WHERE v.video_id = $vid OR v.id = $vid
                    RETURN v.title as title, v.summary as summary, v.topics as topics,
                           v.duration as duration
                    LIMIT 1
                    """,
                    vid=vid,
                )
                video = result.single()

            # Search for the query topic in this video
            with kg.get_session() as session:
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes('frame_search', $query) YIELD node, score
                    WITH node as f, score
                    WHERE f.video_id = $vid
                    RETURN f.timestamp as timestamp, f.description as description, score
                    ORDER BY score DESC
                    LIMIT 3
                    """,
                    query=query,
                    vid=vid,
                )
                frame_matches = list(result)

            # Also search audio
            with kg.get_session() as session:
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes('audio_search', $query) YIELD node, score
                    WITH node as a, score
                    WHERE a.video_id = $vid
                    RETURN a.timestamp as timestamp, a.text as text, score
                    ORDER BY score DESC
                    LIMIT 3
                    """,
                    query=query,
                    vid=vid,
                )
                audio_matches = list(result)

            moments = []
            for m in frame_matches:
                moments.append(
                    {
                        "timestamp": m.get("timestamp", 0),
                        "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                        "type": "visual",
                        "content": (m.get("description") or "")[:200],
                        "score": round(m.get("score", 0), 3),
                    }
                )
            for m in audio_matches:
                moments.append(
                    {
                        "timestamp": m.get("timestamp", 0),
                        "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                        "type": "audio",
                        "content": (m.get("text") or "")[:200],
                        "score": round(m.get("score", 0), 3),
                    }
                )
            moments.sort(key=lambda x: x["score"], reverse=True)

            comparison.append(
                {
                    "video_id": vid,
                    "video_title": (video.get("title") if video else None) or "Untitled",
                    "summary": (video.get("summary") if video else None) or "",
                    "topics": (video.get("topics") if video else None) or [],
                    "duration_formatted": (
                        format_timestamp(video.get("duration", 0))
                        if video and video.get("duration")
                        else None
                    ),
                    "relevant_moments": moments[:5],
                    "relevance_score": round(max((m["score"] for m in moments), default=0), 3),
                }
            )

        # Sort by relevance
        comparison.sort(key=lambda x: x["relevance_score"], reverse=True)

        return {
            "query": query,
            "videos_compared": len(comparison),
            "comparison": comparison,
        }

    except Exception as e:
        return {"error": f"Video comparison failed: {str(e)}", "comparison": []}


@tool
async def find_common_entities(
    entity_type: Annotated[
        str,
        "Type filter: 'person', 'object', 'concept', 'location', or 'any'",
    ] = "any",
    limit: Annotated[int, "Max entities to return"] = 15,
    media_ids: Annotated[list[str] | None, InjectedState("media_ids")] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Find entities (people, objects, concepts) that appear across
    multiple selected videos. Useful for discovering shared themes,
    recurring characters, or common topics.

    Returns entities sorted by how many videos they appear in.
    """
    effective_ids = list(media_ids) if media_ids else []
    if media_id and media_id not in effective_ids:
        effective_ids.append(media_id)

    if len(effective_ids) < 2:
        return {
            "error": "Need at least 2 videos to find common entities.",
            "entities": [],
        }

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        entities = kg.find_common_entities(
            video_ids=effective_ids,
            entity_type=entity_type,
            limit=limit,
        )

        return {
            "entities": entities,
            "total_found": len(entities),
            "videos_analyzed": len(effective_ids),
            "entity_type_filter": entity_type,
        }
    except Exception as e:
        return {"error": str(e), "entities": []}


@tool
async def get_library_overview(
    media_ids: Annotated[list[str] | None, InjectedState("media_ids")] = None,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Get an overview of all selected videos: titles, summaries,
    topics, and durations. Use this to understand what videos
    are loaded before doing cross-video analysis.
    """
    effective_ids = list(media_ids) if media_ids else []
    if media_id and media_id not in effective_ids:
        effective_ids.append(media_id)

    if not effective_ids:
        return {"error": "No videos selected.", "videos": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        videos = kg.get_video_topics(video_ids=effective_ids)

        result = []
        for v in videos:
            result.append(
                {
                    "video_id": v["video_id"],
                    "title": v.get("title") or "Untitled",
                    "summary": (v.get("summary") or "")[:500],
                    "topics": v.get("topics") or [],
                    "duration_formatted": (
                        format_timestamp(v["duration"]) if v.get("duration") else None
                    ),
                }
            )

        all_topics = []
        for v in result:
            all_topics.extend(v.get("topics", []))
        unique_topics = list(dict.fromkeys(all_topics))

        return {
            "videos": result,
            "total_videos": len(result),
            "all_topics": unique_topics[:30],
        }
    except Exception as e:
        return {"error": str(e), "videos": []}


# =============================================================================
# Multi-Video Tool Collection
# =============================================================================

MULTI_VIDEO_TOOLS = [
    search_across_videos,
    compare_videos,
    find_common_entities,
    get_library_overview,
]
