"""
LangGraph Tools — Backward-Compatibility Re-exports
====================================================

All tool implementations have been split into focused modules:
  - search_tools    : Visual/text/entity search, transcript, scene description
  - context_tools   : Chapters, video info, summaries, scene context
  - analysis_tools  : Related content, entity timelines, moment comparison
  - highlight_tools : Highlight detection with multiple strategies
  - multi_video_tools : Cross-video search, comparison, common entities

This module re-exports every public symbol so that existing
``from agent.tools.general import …`` statements continue to work.
"""

from agent.tools.analysis_tools import (  # noqa: F401
    compare_moments,
    get_entity_timeline,
    get_related_content,
)

# --- Context tools ---
from agent.tools.context_tools import (  # noqa: F401
    get_community_overview,
    get_scene_context,
    get_summary,
    get_video_info,
    list_chapters,
)

# --- Highlight tools ---
from agent.tools.highlight_tools import find_highlights  # noqa: F401

# --- Multi-video tools ---
from agent.tools.multi_video_tools import (  # noqa: F401
    MULTI_VIDEO_TOOLS,
    compare_videos,
    find_common_entities,
    get_library_overview,
    search_across_videos,
)
from agent.tools.search_tools import (  # noqa: F401
    describe_scene,
    find_entity,
    get_transcript,
    search_video,
)

# =============================================================================
# Tool Collections
# =============================================================================

SEARCH_TOOLS = [
    search_video,
    find_entity,
    get_transcript,
    describe_scene,
    get_scene_context,
    get_community_overview,
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
]

# Note: Search tools are used by the VideoAgent graph
