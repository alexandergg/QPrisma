"""
Editor Routes

Handles video editor projects and clips management.
This is the foundation for the Chat-to-Edit feature.

Endpoints:
- Projects: CRUD for editor projects
- Clips: Create, update, delete, reorder clips within projects
- Chat: Streaming chat endpoint for Chat-to-Edit
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_editor_route_service
from core.errors import bad_request, forbidden, internal_error, not_found
from models.editor import (
    ClipCreate,
    ClipReorder,
    ClipResponse,
    ClipSubtitleUpdate,
    ClipUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ProjectWithClips,
)
from models.user import User
from services.database_service import get_database_service
from services.editor_route_service import EditorValidationError

router = APIRouter(prefix="/editor", tags=["Editor"])
logger = logging.getLogger(__name__)


# =============================================================================
# Project Endpoints
# =============================================================================


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Create a new editor project from a source video.

    The source video must already be uploaded and processed.
    """
    db = get_database_service()
    media = db.get_media(project_data.source_media_id)
    if not media:
        raise not_found("Source media")
    if media.user_id != current_user.id:
        raise forbidden("Not authorized to use this media")

    service = get_editor_route_service()
    project_dict = service.build_project_create_dict(current_user.id, project_data)
    project = db.create_project(project_dict)
    logger.info(f"Created project {project.id} for user {current_user.id}")
    return project.to_dict()


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all projects for the current user."""
    db = get_database_service()
    projects = db.get_projects_by_user(current_user.id, limit=limit, offset=offset)
    return [p.to_dict() for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectWithClips)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a project with all its clips and source media info."""
    try:
        db = get_database_service()
        project = db.get_project_with_clips(project_id)
        if not project:
            raise not_found("Project")
        if project.user_id != current_user.id:
            raise forbidden("Not authorized")

        service = get_editor_route_service()
        return service.build_project_with_details(project)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting project {project_id}: {e}")
        raise internal_error(detail="Failed to process media request")


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    updates: ProjectUpdate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update a project's metadata."""
    db = get_database_service()
    project = db.get_project(project_id)
    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    update_dict = service.build_project_update_dict(updates)
    if update_dict:
        project = db.update_project(project_id, update_dict)
    return project.to_dict()


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a project and all its clips."""
    db = get_database_service()
    project = db.get_project(project_id)

    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    db.delete_project(project_id)
    logger.info(f"Deleted project {project_id}")


# =============================================================================
# Clip Endpoints
# =============================================================================


@router.post("/projects/{project_id}/clips", response_model=ClipResponse, status_code=201)
async def create_clip(
    project_id: str,
    clip_data: ClipCreate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Create a new clip in a project.

    The clip represents a segment of the source video.
    """
    db = get_database_service()
    project = db.get_project(project_id)
    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    try:
        service.validate_clip_times(
            clip_data.start_time,
            clip_data.end_time,
            db=db,
            source_media_id=project.source_media_id,
        )
    except EditorValidationError as e:
        raise bad_request(str(e))

    clip_dict = service.build_clip_create_dict(project_id, clip_data)
    clip = db.create_clip(clip_dict)
    logger.info(f"Created clip {clip.id} in project {project_id}")
    return clip.to_dict()


@router.get("/projects/{project_id}/clips", response_model=list[ClipResponse])
async def list_clips(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get all clips in a project, ordered by position."""
    db = get_database_service()
    project = db.get_project(project_id)

    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    clips = db.get_clips_by_project(project_id)
    return [clip.to_dict() for clip in clips]


@router.get("/clips/{clip_id}", response_model=ClipResponse)
async def get_clip(
    clip_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a specific clip by ID."""
    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership through project
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    return clip.to_dict()


@router.patch("/clips/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: str,
    updates: ClipUpdate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update a clip's timing or metadata."""
    db = get_database_service()
    clip = db.get_clip(clip_id)
    if not clip:
        raise not_found("Clip")

    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    update_dict = service.build_clip_update_dict(updates)
    try:
        service.validate_clip_update_times(update_dict, clip)
    except EditorValidationError as e:
        raise bad_request(str(e))

    if update_dict:
        clip = db.update_clip(clip_id, update_dict)
    return clip.to_dict()


@router.patch("/clips/{clip_id}/subtitles", response_model=ClipResponse)
async def update_clip_subtitles(
    clip_id: str,
    subtitle_config: ClipSubtitleUpdate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update subtitle configuration for a clip."""
    db = get_database_service()
    clip = db.get_clip(clip_id)
    if not clip:
        raise not_found("Clip")

    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    update_dict = service.build_subtitle_update_dict(subtitle_config)
    clip = db.update_clip(clip_id, update_dict)
    return clip.to_dict()


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip(
    clip_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a clip from its project."""
    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    db.delete_clip(clip_id)
    logger.info(f"Deleted clip {clip_id}")


@router.post("/projects/{project_id}/clips/reorder", response_model=list[ClipResponse])
async def reorder_clips(
    project_id: str,
    reorder_data: ClipReorder,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Reorder clips in a project.

    Provide the clip IDs in the desired order.
    """
    db = get_database_service()
    project = db.get_project(project_id)
    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    try:
        service.validate_reorder_ids(db, project_id, reorder_data.clip_ids)
    except EditorValidationError as e:
        raise bad_request(str(e))

    clips = db.reorder_clips(project_id, reorder_data.clip_ids)
    return [clip.to_dict() for clip in clips]


# =============================================================================
# Bulk Operations
# =============================================================================


@router.post(
    "/projects/{project_id}/clips/bulk",
    response_model=list[ClipResponse],
    status_code=201,
)
async def bulk_create_clips(
    project_id: str,
    clips: list[ClipCreate],
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Create multiple clips at once.

    Useful for adding AI-suggested clips in bulk.
    """
    db = get_database_service()
    project = db.get_project(project_id)
    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_editor_route_service()
    try:
        clips_data = service.validate_and_prepare_bulk_clips(project_id, clips)
    except EditorValidationError as e:
        raise bad_request(str(e))

    created_clips = db.bulk_create_clips(project_id, clips_data)
    logger.info(f"Bulk created {len(created_clips)} clips in project {project_id}")
    return [clip.to_dict() for clip in created_clips]


# =============================================================================
# Subtitle Endpoints
# =============================================================================


class GenerateSubtitlesRequest(BaseModel):
    """Request model for subtitle generation."""

    style: str = Field(
        default="hormozi",
        description="Subtitle style: hormozi, mrbeast, minimal, karaoke, news",
    )


class UpdateSubtitleCueRequest(BaseModel):
    """Request model for updating a subtitle cue."""

    cue_id: int = Field(..., description="ID of the cue to update")
    text: str = Field(..., description="New text for the cue")


@router.get("/subtitle-styles")
async def get_subtitle_styles() -> list[dict[str, Any]]:
    """
    Get available subtitle styles with descriptions.

    Returns a list of styles that can be applied to clips.
    """
    from services.subtitle_service import get_subtitle_service

    service = get_subtitle_service()
    return service.get_available_styles()


@router.post("/clips/{clip_id}/subtitles/generate")
async def generate_clip_subtitles(
    clip_id: str,
    request: GenerateSubtitlesRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Generate subtitles for a clip from the source video's transcription.

    This extracts the relevant portion of the Whisper transcription
    and formats it according to the selected style.
    """
    from services.subtitle_service import get_subtitle_service

    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_subtitle_service()
    result = service.generate_subtitles_for_clip(clip_id, request.style)

    if not result.get("success"):
        raise bad_request(result.get("error", "Failed to generate subtitles"))

    return result


@router.get("/clips/{clip_id}/subtitles")
async def get_clip_subtitles(
    clip_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get subtitle data for a clip.

    Returns the full subtitle data including cues with word-level timing.
    """
    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    if not clip.subtitles_enabled or not clip.subtitles_data:
        return {
            "enabled": False,
            "message": "Subtitles not enabled. Use /generate to create them.",
        }

    return {
        "enabled": True,
        "style": clip.subtitle_style,
        "settings": clip.subtitle_settings,
        "data": clip.subtitles_data,
    }


@router.patch("/clips/{clip_id}/subtitles/cue")
async def update_subtitle_cue(
    clip_id: str,
    request: UpdateSubtitleCueRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Update the text of a specific subtitle cue.

    This allows users to correct transcription errors or modify text.
    """
    from services.subtitle_service import get_subtitle_service

    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    service = get_subtitle_service()
    result = service.update_subtitle_text(clip_id, request.cue_id, request.text)

    if not result.get("success"):
        raise bad_request(result.get("error", "Failed to update cue"))

    return result


@router.get("/clips/{clip_id}/subtitles/srt")
async def export_subtitles_srt(
    clip_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Export subtitles in SRT format.

    Returns downloadable SRT file.
    """
    from fastapi.responses import PlainTextResponse

    from services.subtitle_service import get_subtitle_service

    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    if not clip.subtitles_data:
        raise bad_request("No subtitles on this clip")

    service = get_subtitle_service()
    srt_content = service.generate_srt(clip.subtitles_data)

    return PlainTextResponse(
        content=srt_content,
        media_type="text/srt",
        headers={"Content-Disposition": f'attachment; filename="clip_{clip_id}.srt"'},
    )


# =============================================================================
# Export Endpoints
# =============================================================================


class ExportClipRequest(BaseModel):
    """Request model for exporting a single clip."""

    platform: str = Field(
        default="tiktok",
        description="Target platform: tiktok, reels, shorts, youtube, twitter",
    )
    quality: str = Field(
        default="standard",
        description="Export quality: draft, standard, high, max",
    )
    crop_mode: str | None = Field(
        default=None,
        description="Crop mode: none, center, letterbox, blur_fill. Default: platform default",
    )
    burn_subtitles: bool = Field(
        default=True,
        description="Whether to burn subtitles into the video",
    )


class BatchExportRequest(BaseModel):
    """Request model for batch export."""

    clip_ids: list[str] | None = Field(
        default=None,
        description="Specific clip IDs to export. Null = all clips in project",
    )
    platform: str = Field(default="tiktok")
    quality: str = Field(default="standard")
    crop_mode: str | None = Field(default=None)
    burn_subtitles: bool = Field(default=True)


class EstimateExportRequest(BaseModel):
    """Request model for export estimation."""

    duration_seconds: float = Field(..., description="Duration of the clip in seconds")
    platform: str = Field(default="tiktok")
    quality: str = Field(default="standard")


@router.get("/export/presets")
async def get_export_presets() -> dict[str, Any]:
    """
    Get available export presets.

    Returns platform presets, quality presets, and crop modes.
    """
    from services.export_service import get_export_service

    service = get_export_service()
    return service.get_available_presets()


@router.post("/export/estimate")
async def estimate_export(
    request: EstimateExportRequest,
) -> dict[str, Any]:
    """
    Estimate export time and file size.

    Useful for showing users what to expect before starting export.
    """
    from services.export_service import get_export_service

    service = get_export_service()
    return service.estimate_export_time(
        duration_seconds=request.duration_seconds,
        platform=request.platform,
        quality=request.quality,
    )


@router.post("/clips/{clip_id}/export")
async def export_clip(
    clip_id: str,
    request: ExportClipRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Export a single clip.

    This will:
    1. Cut the video segment from source
    2. Apply aspect ratio conversion if needed
    3. Burn subtitles if enabled
    4. Encode to target format
    5. Upload to storage and return download URL

    The export runs synchronously and returns when complete.
    For large/multiple clips, use the batch endpoint.
    """
    from services.export_service import get_export_service

    db = get_database_service()
    clip = db.get_clip(clip_id)
    if not clip:
        raise not_found("Clip")

    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    db.update_clip(clip_id, {"export_status": "processing"})
    try:
        export_service = get_export_service()
        result = await export_service.export_clip(
            clip_id=clip_id,
            platform=request.platform,
            quality=request.quality,
            crop_mode=request.crop_mode,
            burn_subtitles=request.burn_subtitles,
        )
        service = get_editor_route_service()
        return service.format_export_result(result)
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        db.update_clip(clip_id, {"export_status": "failed"})
        raise internal_error(detail="Failed to process media request")


@router.post("/projects/{project_id}/export/batch")
async def batch_export_clips(
    project_id: str,
    request: BatchExportRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Export multiple clips from a project.

    If clip_ids is not provided, exports all clips in the project.
    Returns results for each clip with success/failure status.
    """
    from services.export_service import get_export_service

    db = get_database_service()
    project = db.get_project(project_id)
    if not project:
        raise not_found("Project")
    if project.user_id != current_user.id:
        raise forbidden("Not authorized")

    export_service = get_export_service()
    results = await export_service.export_clips_batch(
        project_id=project_id,
        clip_ids=request.clip_ids,
        platform=request.platform,
        quality=request.quality,
        crop_mode=request.crop_mode,
        burn_subtitles=request.burn_subtitles,
    )

    service = get_editor_route_service()
    return service.summarize_batch_export_results(results)


@router.get("/clips/{clip_id}/export/status")
async def get_export_status(
    clip_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get the export status of a clip.

    Returns the current export status and download URL if available.
    """
    db = get_database_service()
    clip = db.get_clip(clip_id)

    if not clip:
        raise not_found("Clip")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise forbidden("Not authorized")

    return {
        "clip_id": clip_id,
        "export_status": clip.export_status or "pending",
        "export_url": clip.export_url,
        "export_format": clip.export_format,
    }
