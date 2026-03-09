"""
Agent Tools
===========

LangGraph tools for video search and editor functionality.
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
    get_scene_context,
    get_summary,
    get_video_info,
    list_chapters,
)
from .editor import (
    EDITOR_TOOLS,
    add_subtitles,
    add_suggested_clips,
    change_subtitle_style,
    create_clip,
    delete_clip,
    export_all_clips,
    export_clip,
    generate_auto_clips,
    get_export_status,
    list_clips,
    list_export_presets,
    list_subtitle_styles,
    modify_clip,
    remove_subtitles,
    reorder_clips,
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
    "EDITOR_TOOLS",
    # Search tools
    "search_video",
    "find_entity",
    "get_transcript",
    "describe_scene",
    "get_scene_context",
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
    # Editor tools
    "create_clip",
    "modify_clip",
    "delete_clip",
    "list_clips",
    "reorder_clips",
    "generate_auto_clips",
    "add_suggested_clips",
    "add_subtitles",
    "change_subtitle_style",
    "remove_subtitles",
    "list_subtitle_styles",
    "export_clip",
    "export_all_clips",
    "get_export_status",
    "list_export_presets",
]
