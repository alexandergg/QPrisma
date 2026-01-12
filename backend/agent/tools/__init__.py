"""
Video Agent Tools
=================

Exports all tools available to the video agent.
"""

from agent.tools.search_tools import find_entity, search_video
from agent.tools.navigation_tools import describe_scene, get_transcript
from agent.tools.structure_tools import get_summary, get_video_info, list_chapters
from agent.tools.graph_tools import get_related_content, navigate_timeline

# All tools available to the agent
ALL_TOOLS = [
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

# Tool definitions for Azure OpenAI function calling
TOOL_DEFINITIONS = [tool.definition for tool in ALL_TOOLS]

__all__ = [
    "ALL_TOOLS",
    "TOOL_DEFINITIONS",
    "search_video",
    "find_entity",
    "get_transcript",
    "describe_scene",
    "list_chapters",
    "get_video_info",
    "get_summary",
    "get_related_content",
    "navigate_timeline",
]
