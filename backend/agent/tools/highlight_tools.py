"""
Highlight Tools
===============

LangGraph tools for identifying highlight moments suitable for clips or social media.
Includes multiple detection strategies: frame analysis, scene variety,
entity density, and fallback sampling.

Business logic lives in ``services.highlight_detection_service``; these
tool functions are thin wrappers that provide the LangGraph ``@tool``
interface and ``InjectedState`` plumbing.
"""

import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

logger = logging.getLogger(__name__)


# =============================================================================
# Main Highlight Tool
# =============================================================================


@tool
async def find_highlights(
    criteria: Annotated[
        str, "What makes a moment a highlight: 'engagement', 'action', 'key_topics', 'all'"
    ] = "all",
    max_clips: Annotated[int, "Maximum number of highlight clips to suggest"] = 5,
    min_duration: Annotated[float, "Minimum clip duration in seconds"] = 10.0,
    max_duration: Annotated[float, "Maximum clip duration in seconds"] = 60.0,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Identify highlight moments suitable for clips or social media.
    Returns exportable time ranges with descriptions of why they're highlights.
    """
    if not media_id:
        return {"error": "No video context available.", "highlights": []}

    try:
        from services.highlight_detection_service import HighlightDetectionService
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        if not kg.is_connected:
            kg.connect()

        service = HighlightDetectionService(kg)
        return service.detect_highlights(
            media_id=media_id,
            criteria=criteria,
            max_clips=max_clips,
            min_duration=min_duration,
            max_duration=max_duration,
        )

    except Exception as e:
        return {"error": f"Failed to find highlights: {str(e)}", "highlights": []}
