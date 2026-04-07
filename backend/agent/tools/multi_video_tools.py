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
from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice

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
        return tool_error("no_context", "User context not available.")

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
        data = asdict(result)
        data["_meta"] = tool_meta(
            result_count=sum(len(v.get("results", [])) for v in data.get("results", [])),
        )
        return data
    except Exception as e:
        logger.error("search_across_videos failed: %s", e)
        return tool_error(
            "query_error",
            f"Cross-video search failed: {e}",
            recovery="Use search_video with target_video_id on each video individually.",
        )


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
    effective_ids: list[str] = []
    if media_ids:
        effective_ids = list(media_ids)
    elif media_id:
        effective_ids = [media_id]

    if len(effective_ids) < 2:
        return tool_error(
            "invalid_input",
            f"Compare requires at least 2 videos selected. Currently only "
            f"{len(effective_ids)} video(s) in context.",
            recovery="Ensure multiple videos are selected in library mode before comparing.",
        )

    if not user_id:
        return tool_error("no_context", "User context not available.")

    try:
        from services.cross_video_search_service import get_cross_video_search_service

        svc = get_cross_video_search_service()
        result = svc.compare_videos(query, effective_ids, user_id=user_id)
        data = asdict(result)
        data["_meta"] = tool_meta(result_count=len(effective_ids))
        return data
    except Exception as e:
        logger.error("compare_videos failed: %s", e)
        return tool_error(
            "query_error",
            f"Video comparison failed: {e}",
            recovery=(
                "Use get_summary with target_video_id for each video individually, "
                "then synthesize the comparison from the individual summaries."
            ),
        )


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
        return tool_error(
            "invalid_input",
            "Need at least 2 videos to find common entities.",
        )

    if not user_id:
        return tool_error("no_context", "User context not available.")

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
            "_meta": tool_meta(
                result_count=len(entities),
                total_available=len(entities),
            ),
        }
    except Exception as e:
        logger.error("find_common_entities failed: %s", e)
        return tool_error(
            "query_error",
            f"Finding common entities failed: {e}",
            recovery="Use search_across_videos with entity names to find shared content.",
        )


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
        return tool_error("no_context", "No videos selected.")

    if not user_id:
        return tool_error("no_context", "User context not available.")

    try:
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        videos = kg.get_video_topics(video_ids=effective_ids, user_id=user_id)

        truncated_fields: list[str] = []
        result = []
        for v in videos:
            summary_text, was_cut = truncate_with_notice(v.get("summary") or "", 500)
            if was_cut:
                truncated_fields.append("summary")
            result.append(
                {
                    "video_id": v["video_id"],
                    "title": v.get("title") or "Untitled",
                    "summary": summary_text,
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
            "_meta": tool_meta(
                result_count=len(result),
                total_available=len(effective_ids),
                truncated_fields=list(set(truncated_fields)) if truncated_fields else None,
            ),
        }
    except Exception as e:
        logger.error("get_library_overview failed: %s", e)
        return tool_error("query_error", f"Library overview failed: {e}")


# =============================================================================
# Multi-Video Tool Collection
# =============================================================================

MULTI_VIDEO_TOOLS = [
    search_across_videos,
    compare_videos,
    find_common_entities,
    get_library_overview,
]
