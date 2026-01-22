"""
Editor Routes

Handles video editor projects and clips management.
This is the foundation for the Chat-to-Edit feature.

Endpoints:
- Projects: CRUD for editor projects
- Clips: Create, update, delete, reorder clips within projects
- Chat: Streaming chat endpoint for Chat-to-Edit
"""

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
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

router = APIRouter(prefix="/editor", tags=["Editor"])
logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _get_source_media_info(project) -> dict[str, Any] | None:
    """
    Get source media information with a SAS URL for the video.

    Returns a dict with:
    - id: Media ID
    - filename: Original filename
    - duration: Video duration in seconds
    - blob_url: SAS URL for streaming the video
    """
    from api.routes.media_routes import generate_sas_url

    if not project.source_media:
        return None

    media = project.source_media

    # Extract duration from video_metadata
    duration = None
    if media.video_metadata:
        duration = media.video_metadata.get("duration")

    # Generate SAS URL for the video
    blob_url = None
    if media.blob_name:
        blob_url = generate_sas_url(media.blob_name, expiry_hours=4)

    return {
        "id": media.id,
        "filename": media.original_filename or media.blob_name,
        "duration": duration,
        "blob_url": blob_url,
        "media_type": media.media_type,
        "processed": media.processed,
    }


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

    # Verify source media exists and belongs to user
    media = db.get_media(project_data.source_media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Source media not found")
    if media.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to use this media")

    # Create project
    project = db.create_project(
        {
            "user_id": current_user.id,
            "source_media_id": project_data.source_media_id,
            "name": project_data.name,
            "description": project_data.description,
            "settings": project_data.settings.model_dump() if project_data.settings else {},
        }
    )

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
            raise HTTPException(status_code=404, detail="Project not found")
        if project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

        result = project.to_dict()
        result["clips"] = [clip.to_dict() for clip in project.clips]

        # Include source media info with SAS URL
        result["source_media"] = _get_source_media_info(project)

        logger.info(f"Returning project {project_id} with source_media: {result.get('source_media')}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Build update dict excluding None values
    update_dict = {}
    if updates.name is not None:
        update_dict["name"] = updates.name
    if updates.description is not None:
        update_dict["description"] = updates.description
    if updates.status is not None:
        update_dict["status"] = updates.status.value
    if updates.settings is not None:
        update_dict["settings"] = updates.settings.model_dump()

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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Validate times
    if clip_data.end_time <= clip_data.start_time:
        raise HTTPException(
            status_code=400, detail="end_time must be greater than start_time"
        )

    # Get source video duration to validate
    media = db.get_media(project.source_media_id)
    if media and media.video_metadata:
        duration = media.video_metadata.get("duration", 0)
        if duration > 0 and clip_data.end_time > duration:
            raise HTTPException(
                status_code=400,
                detail=f"end_time ({clip_data.end_time}s) exceeds video duration ({duration}s)",
            )

    clip = db.create_clip(
        {
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
    )

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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership through project
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership through project
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Build update dict
    update_dict = {}
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

    # Validate times if both are being updated
    new_start = update_dict.get("start_time", clip.start_time)
    new_end = update_dict.get("end_time", clip.end_time)
    if new_end <= new_start:
        raise HTTPException(
            status_code=400, detail="end_time must be greater than start_time"
        )

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_dict = {
        "subtitles_enabled": subtitle_config.subtitles_enabled,
        "subtitle_style": subtitle_config.subtitle_style.value,
    }
    if subtitle_config.subtitle_settings:
        update_dict["subtitle_settings"] = subtitle_config.subtitle_settings.model_dump()

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Verify all clip IDs belong to this project
    existing_clips = db.get_clips_by_project(project_id)
    existing_ids = {c.id for c in existing_clips}

    for clip_id in reorder_data.clip_ids:
        if clip_id not in existing_ids:
            raise HTTPException(
                status_code=400, detail=f"Clip {clip_id} not found in project"
            )

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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Validate all clips
    for clip_data in clips:
        if clip_data.end_time <= clip_data.start_time:
            raise HTTPException(
                status_code=400,
                detail="Invalid clip: end_time must be greater than start_time",
            )

    # Convert to dicts
    clips_data = [
        {
            "start_time": c.start_time,
            "end_time": c.end_time,
            "title": c.title,
            "notes": c.notes,
            "order": c.order,
            "is_ai_suggested": c.is_ai_suggested,
            "viral_score": c.viral_score,
            "viral_reasons": c.viral_reasons,
            "transcript_snippet": c.transcript_snippet,
        }
        for c in clips
    ]

    created_clips = db.bulk_create_clips(project_id, clips_data)
    logger.info(f"Bulk created {len(created_clips)} clips in project {project_id}")
    return [clip.to_dict() for clip in created_clips]


# =============================================================================
# Chat-to-Edit Streaming Endpoint
# =============================================================================


class EditorChatRequest(BaseModel):
    """Request model for editor chat endpoint."""

    message: str = Field(..., description="User message for the editor agent")
    session_id: str | None = Field(None, description="Session ID for conversation continuity")
    chat_history: list[dict] | None = Field(
        None, description="Previous messages in the conversation"
    )


@router.post("/projects/{project_id}/chat/stream")
async def editor_chat_stream(
    project_id: str,
    request: EditorChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Streaming chat endpoint for Chat-to-Edit.

    Uses Server-Sent Events (SSE) to stream the agent's response.

    Events emitted:
    - session: Session ID for the conversation
    - thinking: Agent is processing
    - tool_start: Starting a tool call (with tool name)
    - tool_end: Tool call completed (with success status)
    - token: Streaming response token
    - clips_updated: Clips were modified (with updated clips list)
    - done: Final response complete
    - error: Error occurred

    Use with EventSource or fetch with ReadableStream on the client.
    """
    from agent.editor_agent import get_editor_agent
    from agent.memory import get_agent_memory

    # Verify project exists and user has access
    db = get_database_service()
    project = db.get_project_with_clips(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    async def event_generator():
        try:
            agent = get_editor_agent()

            # Handle session
            session_id = request.session_id or str(uuid.uuid4())
            memory = get_agent_memory()
            chat_history = request.chat_history

            # Load or create session
            session = memory.get_session(session_id)
            if session:
                if not chat_history:
                    stored_messages = memory.get_messages(session_id, limit=20)
                    chat_history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in stored_messages
                        if m["role"] in ("user", "assistant") and m.get("content")
                    ]
            else:
                memory.create_session(
                    session_id=session_id,
                    user_id=str(current_user.id) if current_user else None,
                    media_id=str(project.source_media_id),
                )

            # Emit session ID first
            yield f"data: {json.dumps({'event': 'session', 'data': {'session_id': session_id}})}\n\n"

            # Save user message
            memory.add_message(session_id, "user", request.message)

            # Stream agent responses
            final_response = ""
            async for event in agent.run_stream(
                message=request.message,
                project_id=project_id,
                media_id=str(project.source_media_id),
                chat_history=chat_history,
                user_id=str(current_user.id) if current_user else None,
                session_id=session_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Capture final response for memory
                if event.get("event") == "done":
                    final_response = event.get("data", {}).get("response", "")

            # Save assistant message
            if final_response:
                memory.add_message(session_id, "assistant", final_response)

        except Exception as e:
            logger.error(f"Editor chat stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'data': {'error': str(e)}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    service = get_subtitle_service()
    result = service.generate_subtitles_for_clip(clip_id, request.style)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to generate subtitles"),
        )

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    service = get_subtitle_service()
    result = service.update_subtitle_text(clip_id, request.cue_id, request.text)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to update cue"),
        )

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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not clip.subtitles_data:
        raise HTTPException(status_code=400, detail="No subtitles on this clip")

    service = get_subtitle_service()
    srt_content = service.generate_srt(clip.subtitles_data)

    return PlainTextResponse(
        content=srt_content,
        media_type="text/srt",
        headers={
            "Content-Disposition": f'attachment; filename="clip_{clip_id}.srt"'
        },
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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Mark clip as processing
    db.update_clip(clip_id, {"export_status": "processing"})

    try:
        service = get_export_service()
        result = await service.export_clip(
            clip_id=clip_id,
            platform=request.platform,
            quality=request.quality,
            crop_mode=request.crop_mode,
            burn_subtitles=request.burn_subtitles,
        )

        return {
            "success": result.status == "done",
            "clip_id": result.clip_id,
            "status": result.status,
            "output_url": result.output_url,
            "file_size_bytes": result.file_size_bytes,
            "duration_seconds": result.duration_seconds,
            "error": result.error_message,
        }

    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        db.update_clip(clip_id, {"export_status": "failed"})
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    service = get_export_service()
    results = await service.export_clips_batch(
        project_id=project_id,
        clip_ids=request.clip_ids,
        platform=request.platform,
        quality=request.quality,
        crop_mode=request.crop_mode,
        burn_subtitles=request.burn_subtitles,
    )

    # Summarize results
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
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    project = db.get_project(clip.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "clip_id": clip_id,
        "export_status": clip.export_status or "pending",
        "export_url": clip.export_url,
        "export_format": clip.export_format,
    }
