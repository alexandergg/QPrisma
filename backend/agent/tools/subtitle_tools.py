"""
Subtitle Tools
===============

Tools for managing subtitles on clips.
These tools handle subtitle configuration and styling.
Now integrated with SubtitleService for word-level timing.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from services.database_service import get_database_service

logger = logging.getLogger(__name__)

# Available subtitle styles with descriptions
SUBTITLE_STYLES = {
    "hormozi": {
        "name": "Hormozi",
        "description": "Word-by-word, bold, alternating yellow/white colors. Popular for educational/coaching content.",
    },
    "mrbeast": {
        "name": "MrBeast",
        "description": "Large, centered, dramatic shadow, all caps. Great for entertainment content.",
    },
    "minimal": {
        "name": "Minimal",
        "description": "Small, clean, no background. Professional and elegant for podcasts.",
    },
    "karaoke": {
        "name": "Karaoke",
        "description": "Highlights current word being spoken. Dynamic and engaging.",
    },
    "news": {
        "name": "News",
        "description": "Lower third with solid background. Professional news/documentary style.",
    },
}


class AddSubtitlesTool(BaseTool):
    """
    Enable and configure subtitles for a clip.
    Now uses SubtitleService to generate word-level timing from transcription.
    """

    name = "add_subtitles"
    description = (
        "Add subtitles to a clip with a specific style. "
        "This generates subtitles from the video's transcription with word-level timing. "
        "Use this when the user says 'add subtitles', 'put captions', "
        "'add text like Hormozi', or 'I want subtitles on this clip'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to add subtitles to",
            required=True,
        ),
        ToolParameter(
            name="style",
            type="string",
            description="Subtitle style: 'hormozi' (word-by-word bold), 'mrbeast' (large dramatic), 'minimal' (clean), 'karaoke' (highlight current), 'news' (lower third)",
            required=False,
            enum=["hormozi", "mrbeast", "minimal", "karaoke", "news"],
            default="hormozi",
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        style: str = "hormozi",
        **kwargs,
    ) -> dict[str, Any]:
        """Add subtitles to a clip using SubtitleService."""
        try:
            from services.subtitle_service import get_subtitle_service

            db = get_database_service()

            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found.", "success": False}

            # Use SubtitleService to generate subtitles from transcription
            service = get_subtitle_service()
            result = service.generate_subtitles_for_clip(clip_id, style)

            if not result.get("success"):
                # Fallback: just enable subtitles without data
                style_config = SUBTITLE_STYLES.get(style, SUBTITLE_STYLES["hormozi"])
                db.update_clip(clip_id, {
                    "subtitles_enabled": True,
                    "subtitle_style": style,
                })
                return {
                    "success": True,
                    "message": f"Subtitles enabled with '{style_config['name']}' style (no transcription data available).",
                    "clip": {
                        "id": clip.id,
                        "title": clip.title,
                        "range": f"{format_timestamp(float(clip.start_time))} - {format_timestamp(float(clip.end_time))}",
                    },
                    "style": {
                        "name": style_config["name"],
                        "description": style_config["description"],
                    },
                    "warning": result.get("error", "No transcription available"),
                }

            # Success with word-level timing
            style_config = SUBTITLE_STYLES.get(style, SUBTITLE_STYLES["hormozi"])
            subtitle_data = result.get("subtitle_data", {})

            return {
                "success": True,
                "message": f"Subtitles generated with '{style_config['name']}' style.",
                "clip": {
                    "id": clip.id,
                    "title": clip.title,
                    "range": f"{format_timestamp(float(clip.start_time))} - {format_timestamp(float(clip.end_time))}",
                },
                "style": {
                    "name": style_config["name"],
                    "description": style_config["description"],
                },
                "stats": {
                    "word_count": subtitle_data.get("word_count", 0),
                    "cue_count": len(subtitle_data.get("cues", [])),
                },
                "preview": result.get("preview_text", ""),
                "tip": "Subtitles will be burned into the video on export. Edit them in the subtitle panel.",
            }

        except Exception as e:
            logger.error(f"Add subtitles error: {e}")
            return {"error": f"Failed to add subtitles: {str(e)}", "success": False}


class ChangeSubtitleStyleTool(BaseTool):
    """
    Change the subtitle style for a clip that already has subtitles.
    Regenerates cues with the new style's word grouping.
    """

    name = "change_subtitle_style"
    description = (
        "Change the subtitle style on a clip. "
        "Use when user says 'change to MrBeast style', 'make subtitles bigger', "
        "'use a different subtitle look', or 'switch to minimal captions'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to modify",
            required=True,
        ),
        ToolParameter(
            name="style",
            type="string",
            description="New subtitle style",
            required=True,
            enum=["hormozi", "mrbeast", "minimal", "karaoke", "news"],
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        style: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Change subtitle style, regenerating cues if needed."""
        try:
            from services.subtitle_service import get_subtitle_service

            db = get_database_service()

            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found.", "success": False}

            if not clip.subtitles_enabled:
                return {
                    "error": "Subtitles are not enabled on this clip. Use 'add_subtitles' first.",
                    "success": False,
                }

            old_style = clip.subtitle_style or "none"
            style_config = SUBTITLE_STYLES.get(style, SUBTITLE_STYLES["hormozi"])

            # If we have subtitle data with words, regenerate cues with new style
            if clip.subtitles_data and clip.subtitles_data.get("words"):
                service = get_subtitle_service()
                # Regenerate cues with new style grouping
                new_cues = service.generate_subtitle_cues(
                    clip.subtitles_data["words"],
                    style=style,
                )

                # Update subtitle data
                subtitle_data = clip.subtitles_data.copy()
                subtitle_data["cues"] = new_cues
                subtitle_data["style"] = style
                subtitle_data["style_config"] = service.get_style_config(style)

                db.update_clip(clip_id, {
                    "subtitle_style": style,
                    "subtitle_settings": service.get_style_config(style).get("css", {}),
                    "subtitles_data": subtitle_data,
                })
            else:
                # Just update style without regenerating
                db.update_clip(clip_id, {
                    "subtitle_style": style,
                })

            return {
                "success": True,
                "message": f"Subtitle style changed from '{old_style}' to '{style}'.",
                "clip": {
                    "id": clip.id,
                    "title": clip.title,
                },
                "new_style": {
                    "name": style_config["name"],
                    "description": style_config["description"],
                },
            }

        except Exception as e:
            logger.error(f"Change subtitle style error: {e}")
            return {"error": f"Failed to change style: {str(e)}", "success": False}


class RemoveSubtitlesTool(BaseTool):
    """
    Remove subtitles from a clip.
    """

    name = "remove_subtitles"
    description = (
        "Remove subtitles from a clip. "
        "Use when user says 'remove subtitles', 'no captions', "
        "'take off the text', or 'disable subtitles'."
    )
    parameters = [
        ToolParameter(
            name="clip_id",
            type="string",
            description="ID of the clip to remove subtitles from",
            required=True,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        clip_id: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Remove subtitles from a clip."""
        try:
            db = get_database_service()

            clip = db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found.", "success": False}

            if not clip.subtitles_enabled:
                return {
                    "success": True,
                    "message": "Subtitles were already disabled on this clip.",
                }

            db.update_clip(clip_id, {
                "subtitles_enabled": False,
                "subtitle_style": None,
                "subtitle_settings": None,
            })

            return {
                "success": True,
                "message": "Subtitles removed from clip.",
                "clip": {
                    "id": clip.id,
                    "title": clip.title,
                },
            }

        except Exception as e:
            logger.error(f"Remove subtitles error: {e}")
            return {"error": f"Failed to remove subtitles: {str(e)}", "success": False}


class ListSubtitleStylesTool(BaseTool):
    """
    List available subtitle styles.
    """

    name = "list_subtitle_styles"
    description = (
        "Show all available subtitle styles with descriptions. "
        "Use when user asks 'what subtitle styles are available', "
        "'show me caption options', or 'what styles can I use'."
    )
    parameters = []

    async def execute(
        self,
        media_id: str | None,
        **kwargs,
    ) -> dict[str, Any]:
        """List available subtitle styles."""
        styles = []
        for key, config in SUBTITLE_STYLES.items():
            styles.append({
                "id": key,
                "name": config["name"],
                "description": config["description"],
                "best_for": self._get_best_for(key),
            })

        return {
            "styles": styles,
            "message": "Available subtitle styles. Use 'add_subtitles' with your preferred style.",
        }

    def _get_best_for(self, style: str) -> str:
        """Get recommendation for style usage."""
        recommendations = {
            "hormozi": "Educational content, coaching, business tips",
            "mrbeast": "Entertainment, challenges, reactions",
            "minimal": "Podcasts, interviews, professional content",
            "karaoke": "Music, dynamic content, tutorials",
            "news": "News, documentaries, formal presentations",
        }
        return recommendations.get(style, "General use")


# Tool instances
add_subtitles = AddSubtitlesTool()
change_subtitle_style = ChangeSubtitleStyleTool()
remove_subtitles = RemoveSubtitlesTool()
list_subtitle_styles = ListSubtitleStylesTool()
