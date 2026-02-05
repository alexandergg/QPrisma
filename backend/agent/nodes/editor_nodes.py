"""
Editor Agent Nodes
==================

Nodes for the LangGraph-based editor agent.
Uses shared base implementation with editor-specific configuration.
"""

import logging
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.nodes.base import (
    base_call_model,
    base_should_continue,
    select_tools_for_query,
    EDITOR_MAX_TOOL_ITERATIONS,
    EDITOR_WARN_TOOL_ITERATIONS,
)
from agent.prompts import EDITOR_NO_PROJECT_PROMPT, build_editor_prompt
from agent.state.agent_state import (
    AgentState,
    ProjectContext,
)
from agent.tools import EDITOR_TOOLS, SEARCH_TOOLS
from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)

MAX_EDITOR_TOOL_ITERATIONS = EDITOR_MAX_TOOL_ITERATIONS


def get_project_context(project_id: str | None) -> ProjectContext | None:
    """Get current project context for the agent."""
    if not project_id:
        return None

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        project = db.get_project_with_clips(project_id)

        if not project:
            return None

        # Get source video info
        media = db.get_media(project.source_media_id)
        video_duration = 0
        video_title = "Unknown"

        if media:
            video_title = media.original_filename or media.blob_name
            if media.video_metadata:
                video_duration = media.video_metadata.get("duration", 0)

        clips = project.clips or []

        return ProjectContext(
            project_id=project.id,
            project_name=project.name,
            source_media_id=project.source_media_id,
            video_title=video_title,
            video_duration=video_duration,
            clips_count=len(clips),
            clips=[
                {
                    "id": c.id,
                    "order": c.order,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "title": c.title,
                    "subtitle_style": c.subtitle_style if c.subtitles_enabled else None,
                    "viral_score": c.viral_score,
                }
                for c in clips
            ],
        )

    except Exception as e:
        logger.error(f"Failed to get project context: {e}")
        return None


def build_editor_system_message(project_context: ProjectContext | None) -> SystemMessage:
    """Build editor system message with project context."""
    if not project_context:
        return SystemMessage(content=EDITOR_NO_PROJECT_PROMPT)

    # Build clips list string
    clips_list = ""
    for i, clip in enumerate(project_context.get("clips", [])):
        subtitle_info = f" [📝 {clip.get('subtitle_style')}]" if clip.get("subtitle_style") else ""
        viral_info = f" ⭐{int(clip.get('viral_score', 0))}" if clip.get("viral_score") else ""
        clips_list += (
            f"{i + 1}. [{format_timestamp(clip['start_time'])} - {format_timestamp(clip['end_time'])}] "
            f"{clip.get('title') or 'Untitled'}{viral_info}{subtitle_info} (id: {clip['id']})\n"
        )

    total_duration = sum(
        c["end_time"] - c["start_time"] for c in project_context.get("clips", [])
    )

    content = build_editor_prompt(
        project_name=project_context.get("project_name", "Unnamed Project"),
        video_title=project_context.get("video_title", "Unknown"),
        video_duration=format_timestamp(project_context.get("video_duration", 0)),
        clips_count=project_context.get("clips_count", 0),
        total_clips_duration=format_timestamp(total_duration),
        clips_list=clips_list,
    )

    return SystemMessage(content=content)


async def call_editor_model(state: AgentState, config: RunnableConfig) -> dict:
    """
    Call the LLM node for editor agent.

    Binds both search tools and editor tools.
    Uses message trimming to prevent context window overflow.
    Tracks tool call count for iteration management.
    """
    # Build editor system message
    project_context = state.get("project_context")
    system_msg = build_editor_system_message(project_context)
    
    # Combine search and editor tools
    all_tools = SEARCH_TOOLS + EDITOR_TOOLS
    
    # Get user query for dynamic tool selection
    messages = state.get("messages", [])
    user_query = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.type == "human":
            user_query = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
    
    # Dynamic tool binding - select focused subset
    if user_query:
        tools = select_tools_for_query(user_query, all_tools, max_tools=10)
    else:
        tools = all_tools
    
    return await base_call_model(
        state=state,
        config=config,
        tools=tools,
        system_message=system_msg,
        max_iterations=MAX_EDITOR_TOOL_ITERATIONS,
        warn_iterations=EDITOR_WARN_TOOL_ITERATIONS,
        temperature=1,
    )


def should_continue_editor(state: AgentState) -> Literal["tools", "error_handler", "__end__"]:
    """
    Determine if the editor agent should continue or end.

    Checks:
    1. If there are tool calls to execute
    2. If we've exceeded max iterations
    3. If error threshold reached
    """
    return base_should_continue(state, max_iterations=MAX_EDITOR_TOOL_ITERATIONS)
