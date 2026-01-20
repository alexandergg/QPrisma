"""
Video Agent Tools
=================

Exports all tools available to the video agent.
"""

from agent.tools.search_tools import find_entity, search_video
from agent.tools.navigation_tools import describe_scene, get_transcript
from agent.tools.structure_tools import get_summary, get_video_info, list_chapters
from agent.tools.graph_tools import get_related_content, navigate_timeline

# Editor tools for Chat-to-Edit
from agent.tools.editor_tools import (
    create_clip,
    modify_clip,
    delete_clip,
    list_clips,
    reorder_clips,
)
from agent.tools.auto_clip_tools import (
    generate_auto_clips,
    add_suggested_clips,
)
from agent.tools.subtitle_tools import (
    add_subtitles,
    change_subtitle_style,
    remove_subtitles,
    list_subtitle_styles,
)
from agent.tools.export_tools import (
    export_clip,
    export_all_clips,
    get_export_status,
    list_export_presets,
)

# Search and navigation tools (original)
SEARCH_TOOLS = [
    search_video,
    find_entity,
    get_transcript,
    describe_scene,
    list_chapters,
    get_video_info,
    get_summary,
    get_related_content,
    navigate_timeline,
]

# Editor tools (Chat-to-Edit)
EDITOR_TOOLS = [
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
    # Export tools
    export_clip,
    export_all_clips,
    get_export_status,
    list_export_presets,
]

# All tools available to the agent
ALL_TOOLS = SEARCH_TOOLS + EDITOR_TOOLS

# Tool definitions for Azure OpenAI function calling
TOOL_DEFINITIONS = [tool.definition for tool in ALL_TOOLS]

# Separate definitions for different agent modes
SEARCH_TOOL_DEFINITIONS = [tool.definition for tool in SEARCH_TOOLS]
EDITOR_TOOL_DEFINITIONS = [tool.definition for tool in EDITOR_TOOLS]

__all__ = [
    # Collections
    "ALL_TOOLS",
    "SEARCH_TOOLS",
    "EDITOR_TOOLS",
    "TOOL_DEFINITIONS",
    "SEARCH_TOOL_DEFINITIONS",
    "EDITOR_TOOL_DEFINITIONS",
    # Search tools
    "search_video",
    "find_entity",
    "get_transcript",
    "describe_scene",
    "list_chapters",
    "get_video_info",
    "get_summary",
    "get_related_content",
    "navigate_timeline",
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
    # Export tools
    "export_clip",
    "export_all_clips",
    "get_export_status",
    "list_export_presets",
]
