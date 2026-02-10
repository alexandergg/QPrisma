"""
Agent Tools
===========

LangGraph tools for video search and editor functionality.
All tools use the @tool decorator and InjectedState for context.
"""

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
from .general import (
    MULTI_VIDEO_TOOLS,
    SEARCH_TOOLS,
    compare_moments,
    compare_videos,
    describe_scene,
    find_common_entities,
    find_entity,
    find_highlights,
    get_entity_timeline,
    get_library_overview,
    get_related_content,
    get_scene_context,
    get_summary,
    get_transcript,
    get_video_info,
    list_chapters,
    search_across_videos,
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
