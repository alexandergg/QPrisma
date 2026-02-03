"""
LangGraph Editor Tools
======================

Editor-specific tools for the Chat-to-Edit agent.
Uses InjectedState for proper context injection from graph state.
"""

from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.tools.base import format_timestamp

# =============================================================================
# Clip Management Tools
# =============================================================================


@tool
async def create_clip(
    start_time: Annotated[float, "Start time in seconds"],
    end_time: Annotated[float, "End time in seconds"],
    title: Annotated[str | None, "Optional title for the clip"] = None,
    project_id: Annotated[str | None, InjectedState("project_id")] = None,
) -> dict[str, Any]:
    """
    Create a new clip from a time range in the video.
    """
    if not project_id:
        return {"error": "No project context. Create or select a project first."}

    if start_time >= end_time:
        return {"error": "Start time must be before end time."}

    try:
        from services.database_service import get_database_service

        db = get_database_service()

        # Get current clip count for ordering
        project = db.get_project_with_clips(project_id)
        if not project:
            return {"error": "Project not found."}

        order = len(project.clips) if project.clips else 0

        clip = db.create_clip(
            project_id=project_id,
            start_time=start_time,
            end_time=end_time,
            title=title,
            order=order,
        )

        return {
            "success": True,
            "message": f"Created clip '{clip.title or 'Untitled'}' [{format_timestamp(start_time)} - {format_timestamp(end_time)}]",
            "clip": {
                "id": clip.id,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "title": clip.title,
                "order": clip.order,
            },
        }

    except Exception as e:
        return {"error": f"Failed to create clip: {str(e)}"}


@tool
async def modify_clip(
    clip_id: Annotated[str, "ID of the clip to modify"],
    start_time: Annotated[float | None, "New start time in seconds"] = None,
    end_time: Annotated[float | None, "New end time in seconds"] = None,
    title: Annotated[str | None, "New title for the clip"] = None,
    extend_start: Annotated[float | None, "Seconds to extend/shrink start (negative = shrink)"] = None,
    extend_end: Annotated[float | None, "Seconds to extend/shrink end (negative = shrink)"] = None,
) -> dict[str, Any]:
    """
    Modify an existing clip's timing or title.
    Use clip_id from the clips list.
    """
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        clip = db.get_clip(clip_id)

        if not clip:
            return {"error": f"Clip with ID '{clip_id}' not found."}

        # Calculate new times
        new_start = clip.start_time
        new_end = clip.end_time

        if start_time is not None:
            new_start = start_time
        elif extend_start is not None:
            new_start = max(0, clip.start_time - extend_start)

        if end_time is not None:
            new_end = end_time
        elif extend_end is not None:
            new_end = clip.end_time + extend_end

        if new_start >= new_end:
            return {"error": "Invalid time range: start must be before end."}

        # Update clip
        updated = db.update_clip(
            clip_id=clip_id,
            start_time=new_start,
            end_time=new_end,
            title=title if title is not None else clip.title,
        )

        return {
            "success": True,
            "message": f"Updated clip to [{format_timestamp(new_start)} - {format_timestamp(new_end)}]",
            "clip": {
                "id": updated.id,
                "start_time": updated.start_time,
                "end_time": updated.end_time,
                "title": updated.title,
            },
        }

    except Exception as e:
        return {"error": f"Failed to modify clip: {str(e)}"}


@tool
async def delete_clip(
    clip_id: Annotated[str, "ID of the clip to delete"],
) -> dict[str, Any]:
    """
    Delete a clip from the project.
    """
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        clip = db.get_clip(clip_id)

        if not clip:
            return {"error": f"Clip with ID '{clip_id}' not found."}

        title = clip.title or "Untitled"
        db.delete_clip(clip_id)

        return {
            "success": True,
            "message": f"Deleted clip '{title}'.",
        }

    except Exception as e:
        return {"error": f"Failed to delete clip: {str(e)}"}


@tool
async def list_clips(
    project_id: Annotated[str | None, InjectedState("project_id")] = None,
) -> dict[str, Any]:
    """
    List all clips in the current project.
    """
    if not project_id:
        return {"error": "No project context.", "clips": []}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        project = db.get_project_with_clips(project_id)

        if not project:
            return {"error": "Project not found.", "clips": []}

        clips = project.clips or []

        return {
            "project_name": project.name,
            "total_clips": len(clips),
            "clips": [
                {
                    "id": c.id,
                    "order": c.order,
                    "title": c.title or "Untitled",
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "start_formatted": format_timestamp(c.start_time),
                    "end_formatted": format_timestamp(c.end_time),
                    "duration": c.end_time - c.start_time,
                    "subtitles_enabled": c.subtitles_enabled,
                    "subtitle_style": c.subtitle_style,
                    "viral_score": c.viral_score,
                }
                for c in clips
            ],
        }

    except Exception as e:
        return {"error": f"Failed to list clips: {str(e)}", "clips": []}


@tool
async def reorder_clips(
    clip_id: Annotated[str, "ID of the clip to move"],
    new_position: Annotated[int, "New position (0-based index)"],
    project_id: Annotated[str | None, InjectedState("project_id")] = None,
) -> dict[str, Any]:
    """
    Change the order of clips in the timeline.
    """
    if not project_id:
        return {"error": "No project context."}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        db.reorder_clip(project_id, clip_id, new_position)

        return {
            "success": True,
            "message": f"Moved clip to position {new_position + 1}.",
        }

    except Exception as e:
        return {"error": f"Failed to reorder clips: {str(e)}"}


# =============================================================================
# AI-Powered Clips
# =============================================================================


@tool
async def generate_auto_clips(
    count: Annotated[int, "Number of clips to generate"] = 5,
    min_duration: Annotated[float, "Minimum clip duration in seconds"] = 15,
    max_duration: Annotated[float, "Maximum clip duration in seconds"] = 60,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    Use AI to find the best/most viral moments in the video automatically.
    """
    if not media_id:
        return {"error": "No video context.", "suggestions": []}

    try:
        from services.auto_clip_service import get_auto_clip_service

        service = get_auto_clip_service()
        suggestions = await service.generate_clip_suggestions(
            media_id=media_id,
            count=count,
            min_duration=min_duration,
            max_duration=max_duration,
        )

        return {
            "total_suggestions": len(suggestions),
            "suggestions": [
                {
                    "index": i + 1,
                    "start_time": s["start_time"],
                    "end_time": s["end_time"],
                    "start_formatted": format_timestamp(s["start_time"]),
                    "end_formatted": format_timestamp(s["end_time"]),
                    "title": s.get("title", ""),
                    "viral_score": s.get("viral_score", 0),
                    "reason": s.get("reason", ""),
                }
                for i, s in enumerate(suggestions)
            ],
        }

    except Exception as e:
        return {"error": f"Failed to generate auto clips: {str(e)}", "suggestions": []}


@tool
async def add_suggested_clips(
    suggestion_indices: Annotated[list[int], "Indices of suggestions to add (1-based)"],
    suggestions: Annotated[list[dict], "The suggestions list from generate_auto_clips"],
    project_id: Annotated[str | None, InjectedState("project_id")] = None,
) -> dict[str, Any]:
    """
    Add AI-suggested clips to the project.
    Pass the suggestions from generate_auto_clips and indices of which to add.
    """
    if not project_id:
        return {"error": "No project context."}

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        project = db.get_project_with_clips(project_id)

        if not project:
            return {"error": "Project not found."}

        added_clips = []
        current_order = len(project.clips) if project.clips else 0

        for idx in suggestion_indices:
            if 1 <= idx <= len(suggestions):
                s = suggestions[idx - 1]
                clip = db.create_clip(
                    project_id=project_id,
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    title=s.get("title"),
                    order=current_order,
                    viral_score=s.get("viral_score"),
                )
                added_clips.append(clip.title or f"Clip {idx}")
                current_order += 1

        return {
            "success": True,
            "message": f"Added {len(added_clips)} clips: {', '.join(added_clips)}",
            "clips_added": len(added_clips),
        }

    except Exception as e:
        return {"error": f"Failed to add clips: {str(e)}"}


# =============================================================================
# Subtitle Tools
# =============================================================================


@tool
async def add_subtitles(
    clip_id: Annotated[str, "ID of the clip"],
    style: Annotated[str, "Subtitle style: 'hormozi', 'mrbeast', 'minimal', 'karaoke', 'news'"] = "hormozi",
) -> dict[str, Any]:
    """
    Enable subtitles on a clip with a specific style.
    """
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        clip = db.update_clip(
            clip_id=clip_id,
            subtitles_enabled=True,
            subtitle_style=style,
        )

        return {
            "success": True,
            "message": f"Added '{style}' subtitles to clip.",
            "clip_id": clip.id,
            "subtitle_style": style,
        }

    except Exception as e:
        return {"error": f"Failed to add subtitles: {str(e)}"}


@tool
async def change_subtitle_style(
    clip_id: Annotated[str, "ID of the clip"],
    style: Annotated[str, "New subtitle style"],
) -> dict[str, Any]:
    """
    Change the subtitle style on a clip.
    """
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        clip = db.update_clip(clip_id=clip_id, subtitle_style=style)

        return {
            "success": True,
            "message": f"Changed subtitle style to '{style}'.",
            "clip_id": clip.id,
        }

    except Exception as e:
        return {"error": f"Failed to change style: {str(e)}"}


@tool
async def remove_subtitles(
    clip_id: Annotated[str, "ID of the clip"],
) -> dict[str, Any]:
    """
    Disable subtitles on a clip.
    """
    try:
        from services.database_service import get_database_service

        db = get_database_service()
        clip = db.update_clip(clip_id=clip_id, subtitles_enabled=False)

        return {
            "success": True,
            "message": "Removed subtitles from clip.",
            "clip_id": clip.id,
        }

    except Exception as e:
        return {"error": f"Failed to remove subtitles: {str(e)}"}


@tool
async def list_subtitle_styles() -> dict[str, Any]:
    """
    List available subtitle styles with descriptions.
    """
    return {
        "styles": [
            {
                "name": "hormozi",
                "description": "Word-by-word, bold, yellow/white highlights",
                "best_for": "Educational, coaching content",
            },
            {
                "name": "mrbeast",
                "description": "Large, centered, dramatic shadow",
                "best_for": "Entertainment, YouTube",
            },
            {
                "name": "minimal",
                "description": "Small, clean, no background",
                "best_for": "Podcasts, professional content",
            },
            {
                "name": "karaoke",
                "description": "Highlights current word progressively",
                "best_for": "Dynamic, music, tutorials",
            },
            {
                "name": "news",
                "description": "Lower third, solid background",
                "best_for": "News, formal presentations",
            },
        ]
    }


# =============================================================================
# Export Tools
# =============================================================================


@tool
async def export_clip(
    clip_id: Annotated[str, "ID of the clip to export"],
    platform: Annotated[str, "Target platform: 'tiktok', 'reels', 'shorts', 'youtube', 'twitter'"] = "tiktok",
    quality: Annotated[str, "Quality: 'draft', 'standard', 'high', 'max'"] = "standard",
) -> dict[str, Any]:
    """
    Export a clip for a specific platform.
    """
    try:
        from services.export_service import get_export_service

        service = get_export_service()
        job = await service.export_clip(
            clip_id=clip_id,
            platform=platform,
            quality=quality,
        )

        return {
            "success": True,
            "message": f"Export started for {platform}.",
            "job_id": job["id"],
            "status": job["status"],
        }

    except Exception as e:
        return {"error": f"Failed to start export: {str(e)}"}


@tool
async def export_all_clips(
    platform: Annotated[str, "Target platform"] = "tiktok",
    quality: Annotated[str, "Quality level"] = "standard",
    project_id: Annotated[str | None, InjectedState("project_id")] = None,
) -> dict[str, Any]:
    """
    Export all clips in the project.
    """
    if not project_id:
        return {"error": "No project context."}

    try:
        from services.export_service import get_export_service

        service = get_export_service()
        job = await service.export_project(
            project_id=project_id,
            platform=platform,
            quality=quality,
        )

        return {
            "success": True,
            "message": f"Batch export started for {job['clips_count']} clips.",
            "job_id": job["id"],
            "clips_count": job["clips_count"],
        }

    except Exception as e:
        return {"error": f"Failed to start batch export: {str(e)}"}


@tool
async def get_export_status(
    job_id: Annotated[str, "Export job ID"],
) -> dict[str, Any]:
    """
    Check the status of an export job.
    """
    try:
        from services.export_service import get_export_service

        service = get_export_service()
        status = await service.get_job_status(job_id)

        return status

    except Exception as e:
        return {"error": f"Failed to get status: {str(e)}"}


@tool
async def list_export_presets() -> dict[str, Any]:
    """
    List available export platforms and their specifications.
    """
    return {
        "platforms": [
            {
                "name": "tiktok",
                "aspect_ratio": "9:16",
                "resolution": "1080x1920",
                "max_duration": "3 min",
            },
            {
                "name": "reels",
                "aspect_ratio": "9:16",
                "resolution": "1080x1920",
                "max_duration": "90s",
            },
            {
                "name": "shorts",
                "aspect_ratio": "9:16",
                "resolution": "1080x1920",
                "max_duration": "60s",
            },
            {
                "name": "youtube",
                "aspect_ratio": "16:9",
                "resolution": "1920x1080",
                "max_duration": "Unlimited",
            },
            {
                "name": "twitter",
                "aspect_ratio": "16:9",
                "resolution": "1280x720",
                "max_duration": "2:20",
            },
        ],
        "quality_levels": ["draft", "standard", "high", "max"],
    }


# =============================================================================
# Tool Collections
# =============================================================================

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
    export_clip,
    export_all_clips,
    get_export_status,
    list_export_presets,
]
