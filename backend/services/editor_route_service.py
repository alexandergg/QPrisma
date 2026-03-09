"""
Editor Route Service
====================

Business logic extracted from editor route handlers.

Handles clip validation, data transformation, project/clip dict building,
export result formatting, and source media info construction.

Route handlers remain thin (validate input → call service → return response)
while this service owns the domain logic.
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Domain Exceptions
# =============================================================================


class EditorValidationError(ValueError):
    """Raised when editor input validation fails.

    Route handlers should catch this and convert to ``HTTPException(400)``.
    """


# =============================================================================
# Service
# =============================================================================


class EditorRouteService:
    """Business logic for the editor route handlers.

    Dependencies are injected via the constructor so the service remains
    testable without FastAPI or real infrastructure.

    Parameters
    ----------
    sas_url_generator:
        Callable ``(blob_name, expiry_hours) -> url | None`` used to produce
        streaming URLs for source media.  When *None*, blob URLs in
        :meth:`build_source_media_info` will be ``None``.
    """

    def __init__(
        self,
        sas_url_generator: Callable[[str, int], str | None] | None = None,
    ) -> None:
        self._generate_sas_url = sas_url_generator

    # --------------------------------------------------------------------- #
    # Source Media
    # --------------------------------------------------------------------- #

    def build_source_media_info(self, project: Any) -> dict[str, Any] | None:
        """Build a source-media info dict suitable for API responses.

        Returns *None* when the project has no associated source media.
        """
        if not project.source_media:
            return None

        media = project.source_media

        duration = None
        if media.video_metadata:
            duration = media.video_metadata.get("duration")

        blob_url = None
        if media.blob_name and self._generate_sas_url:
            blob_url = self._generate_sas_url(media.blob_name, 4)

        return {
            "id": media.id,
            "filename": media.original_filename or media.blob_name,
            "duration": duration,
            "blob_url": blob_url,
            "media_type": media.media_type,
            "processed": media.processed,
        }

    # --------------------------------------------------------------------- #
    # Project helpers
    # --------------------------------------------------------------------- #

    def build_project_create_dict(self, user_id: str, project_data: Any) -> dict[str, Any]:
        """Convert a ``ProjectCreate`` model into a persistence dict."""
        return {
            "user_id": user_id,
            "source_media_id": project_data.source_media_id,
            "name": project_data.name,
            "description": project_data.description,
            "settings": (project_data.settings.model_dump() if project_data.settings else {}),
        }

    def build_project_update_dict(self, updates: Any) -> dict[str, Any]:
        """Convert a ``ProjectUpdate`` model into a persistence dict.

        Only non-``None`` fields are included.
        """
        update_dict: dict[str, Any] = {}
        if updates.name is not None:
            update_dict["name"] = updates.name
        if updates.description is not None:
            update_dict["description"] = updates.description
        if updates.status is not None:
            update_dict["status"] = updates.status.value
        if updates.settings is not None:
            update_dict["settings"] = updates.settings.model_dump()
        return update_dict

    def build_project_with_details(self, project: Any) -> dict[str, Any]:
        """Build the full project response including clips & source media."""
        result = project.to_dict()
        result["clips"] = [clip.to_dict() for clip in project.clips]
        result["source_media"] = self.build_source_media_info(project)
        return result

    # --------------------------------------------------------------------- #
    # Clip validation
    # --------------------------------------------------------------------- #

    def validate_clip_times(
        self,
        start_time: float,
        end_time: float,
        *,
        db: Any | None = None,
        source_media_id: str | None = None,
    ) -> None:
        """Validate clip start/end times.

        Raises :class:`EditorValidationError` on failure.

        When *db* and *source_media_id* are provided the clip's ``end_time``
        is also validated against the source video duration.
        """
        if end_time <= start_time:
            raise EditorValidationError("end_time must be greater than start_time")

        if db is not None and source_media_id:
            media = db.get_media(source_media_id)
            if media and media.video_metadata:
                duration = media.video_metadata.get("duration", 0)
                if duration > 0 and end_time > duration:
                    raise EditorValidationError(
                        f"end_time ({end_time}s) exceeds video duration ({duration}s)"
                    )

    def validate_clip_update_times(
        self,
        update_dict: dict[str, Any],
        current_clip: Any,
    ) -> None:
        """Validate that updated start/end times are consistent.

        Uses the update dict and falls back to the existing clip values for
        any field not being updated.
        """
        new_start = update_dict.get("start_time", current_clip.start_time)
        new_end = update_dict.get("end_time", current_clip.end_time)
        if new_end <= new_start:
            raise EditorValidationError("end_time must be greater than start_time")

    # --------------------------------------------------------------------- #
    # Clip data building
    # --------------------------------------------------------------------- #

    def build_clip_create_dict(self, project_id: str, clip_data: Any) -> dict[str, Any]:
        """Convert a ``ClipCreate`` model into a persistence dict."""
        return {
            "project_id": project_id,
            "start_time": clip_data.start_time,
            "end_time": clip_data.end_time,
            "title": clip_data.title,
            "notes": clip_data.notes,
            "order": clip_data.order,
            "is_ai_suggested": clip_data.is_ai_suggested,
            "viral_score": clip_data.viral_score,
            "viral_reasons": clip_data.viral_reasons,
            "transcript_snippet": clip_data.transcript_snippet,
        }

    def build_clip_update_dict(self, updates: Any) -> dict[str, Any]:
        """Convert a ``ClipUpdate`` model into a persistence dict.

        Only non-``None`` fields are included.
        """
        update_dict: dict[str, Any] = {}
        if updates.start_time is not None:
            update_dict["start_time"] = updates.start_time
        if updates.end_time is not None:
            update_dict["end_time"] = updates.end_time
        if updates.title is not None:
            update_dict["title"] = updates.title
        if updates.notes is not None:
            update_dict["notes"] = updates.notes
        if updates.order is not None:
            update_dict["order"] = updates.order
        return update_dict

    def build_subtitle_update_dict(self, subtitle_config: Any) -> dict[str, Any]:
        """Convert a ``ClipSubtitleUpdate`` model into a persistence dict."""
        update_dict: dict[str, Any] = {
            "subtitles_enabled": subtitle_config.subtitles_enabled,
            "subtitle_style": subtitle_config.subtitle_style.value,
        }
        if subtitle_config.subtitle_settings:
            update_dict["subtitle_settings"] = subtitle_config.subtitle_settings.model_dump()
        return update_dict

    # --------------------------------------------------------------------- #
    # Bulk / Reorder operations
    # --------------------------------------------------------------------- #

    def validate_and_prepare_bulk_clips(
        self, project_id: str, clips: list[Any]
    ) -> list[dict[str, Any]]:
        """Validate a list of ``ClipCreate`` models and return persistence dicts.

        Raises :class:`EditorValidationError` if any clip has invalid times.
        """
        for clip_data in clips:
            if clip_data.end_time <= clip_data.start_time:
                raise EditorValidationError(
                    "Invalid clip: end_time must be greater than start_time"
                )
        return [self.build_clip_create_dict(project_id, c) for c in clips]

    def validate_reorder_ids(self, db: Any, project_id: str, clip_ids: list[str]) -> None:
        """Ensure every clip ID belongs to the project.

        Raises :class:`EditorValidationError` for unknown IDs.
        """
        existing_clips = db.get_clips_by_project(project_id)
        existing_ids = {c.id for c in existing_clips}
        for clip_id in clip_ids:
            if clip_id not in existing_ids:
                raise EditorValidationError(f"Clip {clip_id} not found in project")

    # --------------------------------------------------------------------- #
    # Export result formatting
    # --------------------------------------------------------------------- #

    def format_export_result(self, result: Any) -> dict[str, Any]:
        """Format a single :class:`ExportProgress` into an API response dict."""
        return {
            "success": result.status == "done",
            "clip_id": result.clip_id,
            "status": result.status,
            "output_url": result.output_url,
            "file_size_bytes": result.file_size_bytes,
            "duration_seconds": result.duration_seconds,
            "error": result.error_message,
        }

    def summarize_batch_export_results(self, results: list[Any]) -> dict[str, Any]:
        """Summarize a list of export results for the batch endpoint."""
        successful = [r for r in results if r.status == "done"]
        failed = [r for r in results if r.status == "failed"]
        return {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "results": [
                {
                    "clip_id": r.clip_id,
                    "status": r.status,
                    "output_url": r.output_url,
                    "file_size_bytes": r.file_size_bytes,
                    "error": r.error_message,
                }
                for r in results
            ],
        }
