"""
Media Routes

Handles media upload, listing, deletion, and retrieval.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import logging
from datetime import UTC, datetime, timedelta

from azure.storage.blob import BlobSasPermissions
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)

from api.dependencies import (
    build_blob_sas_url_async,
    get_blob_service,
    get_current_user,
    get_knowledge_graph_service,
    get_media_or_404,
    get_storage_container_name,
)
from api.dependencies import (
    get_media_library_service as build_media_library_service,
)
from api.dependencies import (
    get_media_upload_service as build_media_upload_service,
)
from api.rate_limit import limiter
from core.errors import forbidden, not_found, service_unavailable
from core.exceptions import (
    BadRequestError,
    ProcessingError,
    QPrismaException,
    ServiceUnavailableError,
    internal_error,
)
from models.user import User
from services.database_service import get_database_service
from services.media_library_service import (
    MediaForbiddenError,
    MediaLibraryService,
    MediaNotFoundError,
    MediaStorageUnavailableError,
)
from services.media_upload_service import MediaUploadService, OptimizedUploadOptions
from services.video_processing_dispatch_service import get_video_processing_dispatch_service

router = APIRouter(tags=["Media"])
logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


async def generate_sas_url(blob_name: str, expiry_hours: int = 1) -> str | None:
    """Generate a SAS URL for reading a blob."""
    return await build_blob_sas_url_async(
        blob_name,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(UTC) + timedelta(hours=expiry_hours),
    )


async def hydrate_data_from_blob(item: dict) -> dict:
    """Hydrate heavy data fields from blob storage."""
    service = build_media_library_service(
        db=get_database_service(),
        blob_service=get_blob_service(),
        container_name=get_storage_container_name(),
        sas_url_factory=generate_sas_url,
    )
    return await service.hydrate_data_from_blob(item)


def get_media_upload_service_instance() -> MediaUploadService:
    return build_media_upload_service(
        blob_service=get_blob_service(),
        db=get_database_service(),
        container_name=get_storage_container_name(),
        dispatch_service_factory=get_video_processing_dispatch_service,
    )


def get_media_library_service_instance() -> MediaLibraryService:
    """Build the media library service using route-level dependency patch points."""
    return build_media_library_service(
        db=get_database_service(),
        blob_service=get_blob_service(),
        container_name=get_storage_container_name(),
        sas_url_factory=generate_sas_url,
        hydrate_data_factory=hydrate_data_from_blob,
        graph_service_factory=get_knowledge_graph_service,
    )


def translate_media_library_error(exc: Exception) -> HTTPException:
    """Translate media service exceptions into the existing HTTP error contract."""
    if isinstance(exc, MediaNotFoundError):
        return not_found("Media")
    if isinstance(exc, MediaForbiddenError):
        return forbidden("You don't have permission to access this media")
    if isinstance(exc, MediaStorageUnavailableError):
        return service_unavailable(str(exc))
    return internal_error()


def translate_media_upload_error(exc: QPrismaException) -> HTTPException:
    """Translate upload service exceptions into HTTP responses."""
    if isinstance(exc, BadRequestError):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, ServiceUnavailableError):
        return HTTPException(status_code=503, detail=exc.message)
    if isinstance(exc, ProcessingError):
        return HTTPException(status_code=500, detail=exc.message)
    return HTTPException(status_code=500, detail="Upload operation failed")


# =============================================================================
# Routes
# =============================================================================


@router.post("/upload")
@limiter.limit("20/minute")
async def upload_media(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    preset: str | None = Form(None),
    max_frames: int | None = Form(None),
):
    """
    Upload a multimedia file (image or video) to Azure Blob Storage.
    Saves metadata to PostgreSQL and starts background processing.
    """
    service = get_media_upload_service_instance()
    try:
        return await service.upload_media(
            file=file,
            user_id=current_user.id,
            preset=preset,
            max_frames=max_frames,
        )
    except QPrismaException as exc:
        raise translate_media_upload_error(exc) from exc


@router.post("/upload/optimized")
@limiter.limit("20/minute")
async def upload_media_optimized(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    preset: str = Form("balanced"),
    max_frames: int = Form(150),
    use_scene_detection: bool = Form(True),
    use_hierarchical_summary: bool = Form(True),
    scene_threshold: float = Form(0.3),
    max_scenes_per_chapter: int = Form(5),
):
    """
    Upload video and process with optimized scene-based pipeline.
    """
    logger.info(f"Upload optimized: {file.filename} by {current_user.email}")

    service = get_media_upload_service_instance()
    try:
        return await service.upload_optimized_video(
            file=file,
            user_id=current_user.id,
            options=OptimizedUploadOptions(
                preset=preset,
                max_frames=max_frames,
                use_scene_detection=use_scene_detection,
                use_hierarchical_summary=use_hierarchical_summary,
                scene_threshold=scene_threshold,
                max_scenes_per_chapter=max_scenes_per_chapter,
            ),
        )
    except QPrismaException as exc:
        raise translate_media_upload_error(exc) from exc


@router.get("/media")
async def list_all_media(
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """List all videos/media for the authenticated user with pagination."""
    try:
        return get_media_library_service_instance().list_media(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        logger.error(f"Error listing media: {e}", exc_info=True)
        raise internal_error() from e


@router.delete("/media/{media_id}")
async def delete_media(media_id: str, current_user: User = Depends(get_current_user)):
    """
    Delete a video and all its associated data:
    - Blob Storage (video file)
    - Neo4j Knowledge Graph (Video, Scenes, Frames, Transcripts, Entities)
    - PostgreSQL (metadata)
    """
    try:
        return await get_media_library_service_instance().delete_media(
            media_id=media_id,
            user_id=current_user.id,
        )
    except (MediaNotFoundError, MediaForbiddenError, MediaStorageUnavailableError) as exc:
        raise translate_media_library_error(exc) from exc
    except Exception as e:
        logger.error(f"Error deleting media {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}")
async def get_media_metadata(media_id: str, current_user: User = Depends(get_current_user)):
    """Get metadata for a multimedia file with signed URL."""
    try:
        return await get_media_library_service_instance().get_media_metadata(
            media_id=media_id,
            user_id=current_user.id,
        )
    except (MediaNotFoundError, MediaForbiddenError, MediaStorageUnavailableError) as exc:
        raise translate_media_library_error(exc) from exc
    except Exception as e:
        logger.error(f"Media lookup failed for {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}/status")
async def get_media_processing_status(
    media_id: str, current_user: User = Depends(get_current_user)
):
    """Get the processing status of a video."""
    get_media_or_404(media_id, current_user)

    try:
        status = get_media_library_service_instance().get_media_processing_status(
            media_id=media_id
        )
        if not status:
            raise not_found("Media")
        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching processing status for {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}/audio")
async def get_video_audio_data(media_id: str, current_user: User = Depends(get_current_user)):
    """
    Get transcription and audio analysis for a processed video.

    Returns:
    - Full transcription with timestamps
    - Audio segments with timing
    - Individual words with timestamps
    - Enriched analysis (summary, topics, sentiment, etc.)
    """
    media = get_media_or_404(media_id, current_user)

    try:
        audio_data = await get_media_library_service_instance().get_video_audio_data(
            media_id=media_id,
            media=media,
        )
        if not audio_data:
            raise not_found(
                "Audio data",
                detail="This video has no audio data or hasn't been processed",
            )

        return audio_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching audio data for {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}/search")
async def search_in_video(
    media_id: str, query: str, top: int = 10, current_user: User = Depends(get_current_user)
):
    """
    Semantic search within a specific video.
    Returns relevant frames with timestamps.
    """
    logger.info("Search request: media_id=%s top=%d", media_id, top)
    get_media_or_404(media_id, current_user)

    try:
        return await get_media_library_service_instance().search_in_video(
            media_id=media_id,
            query=query,
            top=top,
        )
    except Exception as e:
        logger.error(f"Error searching media {media_id}: {e}", exc_info=True)
        raise internal_error() from e
