"""
Agent Tools
===========

LangGraph tools for video search functionality.
All tools use the @tool decorator and InjectedState for context.
"""

# Analysis tools (split from general.py)
from .analysis_tools import (
    compare_moments,
    get_entity_timeline,
    get_related_content,
)

# Context tools (split from general.py)
from .context_tools import (
    get_community_overview,
    get_scene_context,
    get_summary,
    get_video_info,
    list_chapters,
)

# Aggregated collection (re-exported from general.py for backward compat)
from .general import SEARCH_TOOLS  # noqa: F401

# Highlight tools (split from general.py)
from .highlight_tools import find_highlights

# Multi-video tools (split from general.py)
from .multi_video_tools import (
    MULTI_VIDEO_TOOLS,
    compare_videos,
    find_common_entities,
    get_library_overview,
    search_across_videos,
)

# Search tools (split from general.py)
from .search_tools import (
    describe_scene,
    find_entity,
    get_transcript,
    search_video,
)

__all__ = [
    # Tool collections
    "SEARCH_TOOLS",
    "MULTI_VIDEO_TOOLS",
    # Search tools
    "search_video",
    "find_entity",
    "get_transcript",
    "describe_scene",
    "get_scene_context",
    "get_community_overview",
    "list_chapters",
    "get_video_info",
    "get_summary",
    "get_related_content",
    "get_entity_timeline",
    "compare_moments",
    "find_highlights",
    "search_across_videos",
    "compare_videos",
    "find_common_entities",
    "get_library_overview",
]
