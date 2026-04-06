"""
Multi-Video Tools
=================

LangGraph tools for cross-video search, comparison, and analysis.
Tool functions are thin wrappers that delegate to
:class:`~services.cross_video_search_service.CrossVideoSearchService`.
"""

import logging
from dataclasses import asdict
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
    if not user_id:
        return {"error": "User context not available.", "results": []}

    try:
        from services.cross_video_search_service import get_cross_video_search_service

        svc = get_cross_video_search_service()
        result = svc.search_across_videos(
            query,
            limit_per_video=limit_per_video,
            max_videos=max_videos,
            media_ids=media_ids,
            user_id=user_id,
        )
        return asdict(result)
    except Exception as e:
        return {
            "error": f"Cross-video search failed: {str(e)}",
            "results": [],
            "fallback_suggestion": (
                "Use search_video with target_video_id on each video individually."
            ),
        }


@tool
async def compare_videos(
    query: Annotated[
        str,
        "What aspect to compare across the selected videos "
        "(e.g., 'revenue growth', 'main topics', 'speakers')",
    ],
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
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
            "fallback_suggestion": (
                "Ensure multiple videos are selected in library mode before comparing."
            ),
        }

    if not user_id:
        return {
            "error": "User context not available.",
            "comparison": [],
        }

    try:
        from services.cross_video_search_service import get_cross_video_search_service

        svc = get_cross_video_search_service()
        result = svc.compare_videos(query, effective_ids, user_id=user_id)
        return asdict(result)
    except Exception as e:
        return {
            "error": f"Video comparison failed: {str(e)}",
            "comparison": [],
            "videos_attempted": len(effective_ids),
            "fallback_suggestion": (
                "Use get_summary with target_video_id for each video individually, "
                "then synthesize the comparison from the individual summaries."
            ),
        }


@tool
async def find_common_entities(
    entity_type: Annotated[
        str,
        "Type filter: 'person', 'object', 'concept', 'location', or 'any'",
    ] = "any",
    limit: Annotated[int, "Max entities to return"] = 15,
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
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

    if not user_id:
        return {
            "error": "User context not available.",
            "entities": [],
        }

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        entities = kg.find_common_entities(
            video_ids=effective_ids,
            entity_type=entity_type,
            limit=limit,
            user_id=user_id,
        )

        return {
            "entities": entities,
            "total_found": len(entities),
            "videos_analyzed": len(effective_ids),
            "entity_type_filter": entity_type,
        }
    except Exception as e:
        return {
            "error": f"Finding common entities failed: {str(e)}",
            "entities": [],
            "videos_attempted": len(effective_ids),
            "fallback_suggestion": (
                "Use search_across_videos with entity names to find shared content."
            ),
        }


@tool
async def get_library_overview(
    user_id: Annotated[str | None, InjectedState("user_id")] = None,
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

    if not user_id:
        return {"error": "User context not available.", "videos": []}

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        videos = kg.get_video_topics(video_ids=effective_ids, user_id=user_id)

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
