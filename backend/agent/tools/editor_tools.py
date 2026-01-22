"""
Editor Tools
=============

Tools for video editing operations via Chat-to-Edit.
These tools allow the agent to create, modify, and manage clips
within editor projects.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.database_service import get_database_service

logger = logging.getLogger(__name__)


class CreateClipTool(BaseTool):
    """
    Create a new clip in the current editor project.

    The agent uses this when the user wants to create a clip
    from a specific moment in the video.
    """

    name = "create_clip"
    description = (
        "Create a new clip in the current project from a specific time range. "
        "Use this when the user says things like 'create a clip', 'add this moment', "
        "'make a clip from X to Y', or after finding a moment they want to save."
    )
    parameters = [
        ToolParameter(
            name="start_time",
            type="number",
            description="Start time of the clip in seconds",
            required=True,
        ),
        ToolParameter(
            name="end_time",
            type="number",
            description="End time of the clip in seconds",
            required=True,
        ),
        ToolParameter(
            name="title",
            type="string",
            description="Optional title for the clip (e.g., 'Introduction to AI', 'Key moment')",
            required=False,
        ),
        ToolParameter(
            name="notes",
            type="string",
            description="Optional notes about why this clip was created",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        start_time: float,
        end_time: float,
        title: str | None = None,
        notes: str | None = None,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a new clip."""
        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        if end_time <= start_time:
            return {
                "error": "End time must be greater than start time.",
                "success": False,
            }

        try:
            db = get_database_service()

            # Get project to verify it exists
            project = db.get_project(project_id)
            if not project:
                return {"error": "Project not found.", "success": False}

            # Get video duration to validate
            if media_id:
                media = db.get_media(media_id)
                if media and media.video_metadata:
                    duration = media.video_metadata.get("duration", 0)
                    if duration > 0 and end_time > duration:
                        return {
                            "error": f"End time ({end_time}s) exceeds video duration ({duration}s).",
                            "success": False,
                        }

            # Create the clip
            clip = db.create_clip({
                "project_id": project_id,
                "start_time": start_time,
                "end_time": end_time,
                "title": title,
                "notes": notes,
                "is_ai_suggested": False,
            })

            duration = end_time - start_time
            return {
                "success": True,
                "message": f"Clip created [{format_timestamp(start_time)} - {format_timestamp(end_time)}]",
                "clip": {
                    "id": clip.id,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "start_formatted": format_timestamp(start_time),
                    "end_formatted": format_timestamp(end_time),
                    "duration": round(duration, 1),
                    "duration_formatted": format_timestamp(duration),
                    "title": clip.title,
                    "order": clip.order,
                },
            }

        except Exception as e:
            logger.error(f"Create clip error: {e}")
            return {"error": f"Failed to create clip: {str(e)}", "success": False}


class ModifyClipTool(BaseTool):
    """
    Modify an existing clip's timing or metadata.

    The agent uses this when the user wants to adjust a clip.
    """

    name = "modify_clip"
    description = (
        "Modify an existing clip's start time, end time, or title. "
        "Use this when the user says 'make it longer', 'make it shorter', "
        "'extend the clip', 'trim the beginning', or 'rename the clip'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to modify",
            required=True,
        ),
        ToolParameter(
            name="start_time",
            type="number",
            description="New start time in seconds (optional)",
            required=False,
        ),
        ToolParameter(
            name="end_time",
            type="number",
            description="New end time in seconds (optional)",
            required=False,
        ),
        ToolParameter(
            name="title",
            type="string",
            description="New title for the clip (optional)",
            required=False,
        ),
        ToolParameter(
            name="extend_start",
            type="number",
            description="Seconds to add/remove from start (negative = earlier, positive = later)",
            required=False,
        ),
        ToolParameter(
            name="extend_end",
            type="number",
            description="Seconds to add/remove from end (positive = longer, negative = shorter)",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        start_time: float | None = None,
        end_time: float | None = None,
        title: str | None = None,
        extend_start: float | None = None,
        extend_end: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Modify an existing clip."""
        try:
            db = get_database_service()

            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found.", "success": False}

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

            if new_end <= new_start:
                return {
                    "error": "Invalid time range: end must be greater than start.",
                    "success": False,
                }

            # Build update dict
            updates = {}
            if new_start != clip.start_time:
                updates["start_time"] = new_start
            if new_end != clip.end_time:
                updates["end_time"] = new_end
            if title is not None:
                updates["title"] = title

            if not updates:
                return {
                    "success": True,
                    "message": "No changes made.",
                    "clip": {
                        "id": clip.id,
                        "start_formatted": format_timestamp(clip.start_time),
                        "end_formatted": format_timestamp(clip.end_time),
                    },
                }

            updated_clip = db.update_clip(clip_id, updates)

            old_duration = clip.end_time - clip.start_time
            new_duration = new_end - new_start
            duration_change = new_duration - old_duration

            return {
                "success": True,
                "message": f"Clip updated: [{format_timestamp(new_start)} - {format_timestamp(new_end)}]",
                "clip": {
                    "id": updated_clip.id,
                    "start_time": updated_clip.start_time,
                    "end_time": updated_clip.end_time,
                    "start_formatted": format_timestamp(new_start),
                    "end_formatted": format_timestamp(new_end),
                    "duration": round(new_duration, 1),
                    "duration_change": round(duration_change, 1),
                    "title": updated_clip.title,
                },
            }

        except Exception as e:
            logger.error(f"Modify clip error: {e}")
            return {"error": f"Failed to modify clip: {str(e)}", "success": False}


class DeleteClipTool(BaseTool):
    """
    Delete a clip from the project.
    """

    name = "delete_clip"
    description = (
        "Delete a clip from the current project. "
        "Use this when the user says 'remove this clip', 'delete clip X', "
        "'I don't want this one', or 'discard that'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to delete",
            required=True,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Delete a clip."""
        try:
            db = get_database_service()

            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found.", "success": False}

            # Store info for response
            clip_info = {
                "id": clip.id,
                "title": clip.title,
                "start_formatted": format_timestamp(clip.start_time),
                "end_formatted": format_timestamp(clip.end_time),
            }

            db.delete_clip(clip_id)

            return {
                "success": True,
                "message": f"Clip deleted: [{clip_info['start_formatted']} - {clip_info['end_formatted']}]",
                "deleted_clip": clip_info,
            }

        except Exception as e:
            logger.error(f"Delete clip error: {e}")
            return {"error": f"Failed to delete clip: {str(e)}", "success": False}


class ListClipsTool(BaseTool):
    """
    List all clips in the current project.
    """

    name = "list_clips"
    description = (
        "Get a list of all clips in the current project with their timing and details. "
        "Use this when the user asks 'what clips do I have', 'show me the clips', "
        "'list all clips', or to understand the current state of the project."
    )
    parameters = [
        ToolParameter(
            name="include_details",
            type="boolean",
            description="Include full details like notes and AI scores (default: false)",
            required=False,
            default=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        include_details: bool = False,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """List all clips in the project."""
        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "clips": [],
            }

        try:
            db = get_database_service()

            project = db.get_project(project_id)
            if not project:
                return {"error": "Project not found.", "clips": []}

            clips = db.get_clips_by_project(project_id)

            clips_list = []
            total_duration = 0

            for clip in clips:
                duration = clip.end_time - clip.start_time
                total_duration += duration

                clip_info = {
                    "id": clip.id,
                    "order": clip.order + 1,  # 1-indexed for display
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "start_formatted": format_timestamp(clip.start_time),
                    "end_formatted": format_timestamp(clip.end_time),
                    "duration": round(duration, 1),
                    "duration_formatted": format_timestamp(duration),
                    "title": clip.title or f"Clip {clip.order + 1}",
                }

                if include_details:
                    clip_info.update({
                        "notes": clip.notes,
                        "is_ai_suggested": clip.is_ai_suggested,
                        "viral_score": clip.viral_score,
                        "subtitle_style": clip.subtitle_style,
                        "export_status": clip.export_status,
                    })

                clips_list.append(clip_info)

            return {
                "project_name": project.name,
                "total_clips": len(clips_list),
                "total_duration": round(total_duration, 1),
                "total_duration_formatted": format_timestamp(total_duration),
                "clips": clips_list,
            }

        except Exception as e:
            logger.error(f"List clips error: {e}")
            return {"error": f"Failed to list clips: {str(e)}", "clips": []}


class ReorderClipsTool(BaseTool):
    """
    Reorder clips in the project timeline.
    """

    name = "reorder_clips"
    description = (
        "Change the order of clips in the timeline. "
        "Use this when the user says 'move this clip to the end', "
        "'put clip 2 first', 'swap clips', or 'reorder the clips'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to move",
            required=True,
        ),
        ToolParameter(
            name="new_position",
            type="integer",
            description="New position in the timeline (1-indexed, 1 = first)",
            required=True,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        new_position: int,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Reorder a clip to a new position."""
        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        try:
            db = get_database_service()

            clips = db.get_clips_by_project(project_id)
            if not clips:
                return {"error": "No clips in project.", "success": False}

            # Find the clip to move
            clip_ids = [c.id for c in clips]
            if clip_id not in clip_ids:
                return {"error": "Clip not found in project.", "success": False}

            # Validate position (1-indexed)
            if new_position < 1 or new_position > len(clips):
                return {
                    "error": f"Invalid position. Must be between 1 and {len(clips)}.",
                    "success": False,
                }

            # Remove clip from current position and insert at new position
            clip_ids.remove(clip_id)
            clip_ids.insert(new_position - 1, clip_id)

            # Reorder all clips
            updated_clips = db.reorder_clips(project_id, clip_ids)

            # Find the moved clip's new info
            moved_clip = next((c for c in updated_clips if c.id == clip_id), None)

            return {
                "success": True,
                "message": f"Clip moved to position {new_position}",
                "clip": {
                    "id": clip_id,
                    "new_position": new_position,
                    "title": moved_clip.title if moved_clip else None,
                },
                "new_order": [
                    {
                        "position": i + 1,
                        "clip_id": c.id,
                        "title": c.title or f"Clip {i + 1}",
                        "range": f"{format_timestamp(c.start_time)} - {format_timestamp(c.end_time)}",
                    }
                    for i, c in enumerate(updated_clips)
                ],
            }

        except Exception as e:
            logger.error(f"Reorder clips error: {e}")
            return {"error": f"Failed to reorder clips: {str(e)}", "success": False}


# Tool instances
create_clip = CreateClipTool()
modify_clip = ModifyClipTool()
delete_clip = DeleteClipTool()
list_clips = ListClipsTool()
reorder_clips = ReorderClipsTool()
