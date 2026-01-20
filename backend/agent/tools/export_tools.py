"""
Export Tools
============

Tools for exporting video clips via Chat-to-Edit.
These tools allow the agent to export clips to various platforms
like TikTok, Instagram Reels, YouTube Shorts, etc.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.database_service import get_database_service

logger = logging.getLogger(__name__)


class ExportClipTool(BaseTool):
    """
    Export a single clip to a specific platform format.

    The agent uses this when the user wants to export a clip
    for TikTok, Reels, Shorts, YouTube, etc.
    """

    name = "export_clip"
    description = (
        "Export a clip to a specific platform format. "
        "Use this when the user says 'export to TikTok', 'download this clip', "
        "'export for Reels', 'make it ready for YouTube', or similar requests. "
        "Available platforms: tiktok, reels, shorts, youtube, twitter. "
        "Available qualities: draft (fast preview), standard (recommended), high, max."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to export",
            required=True,
        ),
        ToolParameter(
            name="platform",
            type="string",
            description="Target platform: tiktok, reels, shorts, youtube, twitter. Default: tiktok",
            required=False,
        ),
        ToolParameter(
            name="quality",
            type="string",
            description="Export quality: draft (fast), standard (recommended), high, max. Default: standard",
            required=False,
        ),
        ToolParameter(
            name="burn_subtitles",
            type="boolean",
            description="Whether to burn subtitles into the video. Default: true",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        platform: str = "tiktok",
        quality: str = "standard",
        burn_subtitles: bool = True,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Export a clip to the specified platform."""
        from services.export_service import get_export_service

        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        try:
            db = get_database_service()

            # Verify clip exists and belongs to project
            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": f"Clip {clip_id} not found.", "success": False}

            if clip.project_id != project_id:
                return {"error": "Clip does not belong to this project.", "success": False}

            # Validate platform
            valid_platforms = ["tiktok", "reels", "shorts", "youtube", "twitter"]
            if platform.lower() not in valid_platforms:
                return {
                    "error": f"Invalid platform '{platform}'. Available: {', '.join(valid_platforms)}",
                    "success": False,
                }

            # Validate quality
            valid_qualities = ["draft", "standard", "high", "max"]
            if quality.lower() not in valid_qualities:
                return {
                    "error": f"Invalid quality '{quality}'. Available: {', '.join(valid_qualities)}",
                    "success": False,
                }

            # Mark as processing
            db.update_clip(clip_id, {"export_status": "processing"})

            # Export the clip
            service = get_export_service()
            result = await service.export_clip(
                clip_id=clip_id,
                platform=platform.lower(),
                quality=quality.lower(),
                burn_subtitles=burn_subtitles,
            )

            if result.status == "done":
                duration = clip.end_time - clip.start_time
                file_size_mb = (result.file_size_bytes or 0) / 1024 / 1024

                return {
                    "success": True,
                    "message": f"Clip exported for {platform.upper()}!",
                    "export": {
                        "clip_id": clip_id,
                        "platform": platform,
                        "quality": quality,
                        "download_url": result.output_url,
                        "duration": format_timestamp(duration),
                        "file_size": f"{file_size_mb:.1f} MB",
                        "subtitles_burned": burn_subtitles and clip.subtitles_enabled,
                    },
                }
            else:
                return {
                    "success": False,
                    "error": result.error_message or "Export failed",
                    "status": result.status,
                }

        except Exception as e:
            logger.error(f"Export clip error: {e}")
            return {"error": f"Failed to export clip: {str(e)}", "success": False}


class ExportAllClipsTool(BaseTool):
    """
    Export all clips in the project to a specific platform format.

    The agent uses this when the user wants to export multiple
    or all clips at once.
    """

    name = "export_all_clips"
    description = (
        "Export all clips in the current project to a specific platform format. "
        "Use this when the user says 'export all clips', 'export everything', "
        "'download all my clips', or 'batch export'. "
        "You can also specify specific clip IDs to export a subset."
    )
    parameters = [
        ToolParameter(
            name="platform",
            type="string",
            description="Target platform: tiktok, reels, shorts, youtube, twitter. Default: tiktok",
            required=False,
        ),
        ToolParameter(
            name="quality",
            type="string",
            description="Export quality: draft, standard, high, max. Default: standard",
            required=False,
        ),
        ToolParameter(
            name="clip_ids",
            type="array",
            description="Optional list of specific clip IDs to export. If not provided, exports all clips.",
            required=False,
        ),
        ToolParameter(
            name="burn_subtitles",
            type="boolean",
            description="Whether to burn subtitles into the videos. Default: true",
            required=False,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        platform: str = "tiktok",
        quality: str = "standard",
        clip_ids: list[str] | None = None,
        burn_subtitles: bool = True,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Export all or specified clips from the project."""
        from services.export_service import get_export_service

        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        try:
            db = get_database_service()

            # Get all clips in project
            all_clips = db.list_clips(project_id)
            if not all_clips:
                return {"error": "No clips in project to export.", "success": False}

            # Filter to specified clip IDs if provided
            if clip_ids:
                all_clip_ids = {c.id for c in all_clips}
                invalid_ids = set(clip_ids) - all_clip_ids
                if invalid_ids:
                    return {
                        "error": f"Clips not found: {', '.join(invalid_ids)}",
                        "success": False,
                    }
                clips_to_export = [c for c in all_clips if c.id in clip_ids]
            else:
                clips_to_export = all_clips

            # Export clips
            service = get_export_service()
            results = await service.export_clips_batch(
                project_id=project_id,
                clip_ids=[c.id for c in clips_to_export] if clip_ids else None,
                platform=platform.lower(),
                quality=quality.lower(),
                burn_subtitles=burn_subtitles,
            )

            # Summarize results
            successful = [r for r in results if r.status == "done"]
            failed = [r for r in results if r.status == "failed"]

            exports = []
            for r in successful:
                clip = next((c for c in clips_to_export if c.id == r.clip_id), None)
                if clip:
                    file_size_mb = (r.file_size_bytes or 0) / 1024 / 1024
                    exports.append({
                        "clip_id": r.clip_id,
                        "title": clip.title or f"Clip {clip.order}",
                        "download_url": r.output_url,
                        "file_size": f"{file_size_mb:.1f} MB",
                    })

            message = f"Exported {len(successful)} of {len(results)} clips for {platform.upper()}."
            if failed:
                message += f" {len(failed)} failed."

            return {
                "success": len(successful) > 0,
                "message": message,
                "total": len(results),
                "successful": len(successful),
                "failed": len(failed),
                "platform": platform,
                "quality": quality,
                "exports": exports,
                "errors": [
                    {"clip_id": r.clip_id, "error": r.error_message}
                    for r in failed
                ] if failed else None,
            }

        except Exception as e:
            logger.error(f"Export all clips error: {e}")
            return {"error": f"Failed to export clips: {str(e)}", "success": False}


class GetExportStatusTool(BaseTool):
    """
    Get the export status of a clip.

    The agent uses this to check on export progress or
    retrieve download links for previously exported clips.
    """

    name = "get_export_status"
    description = (
        "Get the export status and download URL for a clip. "
        "Use this when the user asks 'is it done?', 'where's my download?', "
        "'what's the status of the export?', or similar questions."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to check",
            required=True,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Get export status for a clip."""
        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        try:
            db = get_database_service()
            clip = db.get_clip(clip_id)

            if not clip:
                return {"error": f"Clip {clip_id} not found.", "success": False}

            if clip.project_id != project_id:
                return {"error": "Clip does not belong to this project.", "success": False}

            status = clip.export_status or "pending"

            result = {
                "success": True,
                "clip_id": clip_id,
                "title": clip.title,
                "status": status,
            }

            if status == "done" and clip.export_url:
                result["download_url"] = clip.export_url
                result["format"] = clip.export_format
                result["message"] = f"Export complete! Download ready for {clip.export_format or 'video'}."
            elif status == "processing":
                result["message"] = "Export is still processing..."
            elif status == "failed":
                result["message"] = "Export failed. Try exporting again."
            else:
                result["message"] = "Not exported yet. Use export_clip to export."

            return result

        except Exception as e:
            logger.error(f"Get export status error: {e}")
            return {"error": f"Failed to get status: {str(e)}", "success": False}


class ListExportPresetsToolTool(BaseTool):
    """
    List available export presets and platforms.

    The agent uses this when the user asks about available
    export options or platform specifications.
    """

    name = "list_export_presets"
    description = (
        "List available export platforms and quality presets. "
        "Use this when the user asks 'what formats can you export?', "
        "'what platforms are supported?', or 'what quality options are there?'."
    )
    parameters = []

    async def execute(
        self,
        media_id: str | None,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """List available export presets."""
        from services.export_service import get_export_service

        try:
            service = get_export_service()
            presets = service.get_available_presets()

            platforms_list = []
            for name, info in presets["platforms"].items():
                platforms_list.append(
                    f"• **{info['display_name']}** ({name}): {info['resolution']}, "
                    f"aspect ratio {info['aspect_ratio']}"
                    + (f", max {info['max_duration']}s" if info['max_duration'] else "")
                )

            qualities_list = []
            for name, info in presets["qualities"].items():
                qualities_list.append(f"• **{name}**: {info['description']}")

            return {
                "success": True,
                "platforms": presets["platforms"],
                "qualities": presets["qualities"],
                "crop_modes": presets["crop_modes"],
                "summary": {
                    "platforms": "\n".join(platforms_list),
                    "qualities": "\n".join(qualities_list),
                },
            }

        except Exception as e:
            logger.error(f"List export presets error: {e}")
            return {"error": f"Failed to get presets: {str(e)}", "success": False}


# Tool instances
export_clip = ExportClipTool()
export_all_clips = ExportAllClipsTool()
get_export_status = GetExportStatusTool()
list_export_presets = ListExportPresetsToolTool()

# Export all tools
EXPORT_TOOLS = [
    export_clip,
    export_all_clips,
    get_export_status,
    list_export_presets,
]
