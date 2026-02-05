"""
Agent Tools
===========

LangGraph tools for video search and editor functionality.
All tools use the @tool decorator and InjectedState for context.
"""

from .general import (
    SEARCH_TOOLS,
    MULTI_VIDEO_TOOLS,
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
    compare_videos,
    find_common_entities,
    get_library_overview,
)
from .editor import (
    EDITOR_TOOLS,
    create_clip,
    modify_clip,
    delete_clip,
    list_clips,
    reorder_clips,
    generate_auto_clips,
    add_suggested_clips,
    add_subtitles,
    change_subtitle_style,
    remove_subtitles,
    list_subtitle_styles,
    export_clip,
    export_all_clips,
    get_export_status,
    list_export_presets,
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

