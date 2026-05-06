"""
Media Routes

Handles media upload, listing, deletion, and retrieval.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import asyncio
import json
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
from api.rate_limit import limiter
from core.degraded import DegradationImpact, record_degraded_operation
from core.errors import forbidden, not_found, service_unavailable
from core.exceptions import internal_error
from models.user import User
from services.database_service import get_database_service
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
    blob_service = get_blob_service()
    if not blob_service:
        return item

    storage_container = get_storage_container_name()
    loop = asyncio.get_running_loop()

    # 1. Hydrate Audio Data
    if item.get("audio_data_blob") and (
        not item.get("audio_data") or "transcription" not in item.get("audio_data", {})
    ):
        try:
            blob_client = blob_service.get_blob_client(
                container=storage_container, blob=item["audio_data_blob"]
            )
            audio_json = await loop.run_in_executor(
                None, lambda: blob_client.download_blob().readall()
            )
            item["audio_data"] = json.loads(audio_json)
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="media",
                operation="hydrate_audio_data",
                impact=DegradationImpact.BLOB_HYDRATION,
                exc=exc,
            )

    # 2. Hydrate Objects Data
    if item.get("objects_data_blob") and (
        not item.get("objects_data") or "frames" not in item.get("objects_data", {})
    ):
        try:
            blob_client = blob_service.get_blob_client(
                container=storage_container, blob=item["objects_data_blob"]
            )
            objects_json = await loop.run_in_executor(
                None, lambda: blob_client.download_blob().readall()
            )
            item["objects_data"] = json.loads(objects_json)
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="media",
                operation="hydrate_objects_data",
                impact=DegradationImpact.BLOB_HYDRATION,
                exc=exc,
            )

    # 3. Hydrate Frames Data
    if item.get("frames_data_blob"):
        try:
            blob_client = blob_service.get_blob_client(
                container=storage_container, blob=item["frames_data_blob"]
            )
            frames_json = await loop.run_in_executor(
                None, lambda: blob_client.download_blob().readall()
            )
            frames_data = json.loads(frames_json)
            item["frames_data"] = frames_data

            # Map to objects_data for frontend compatibility
            if not item.get("objects_data"):
                mapped_frames = []
                for frame in frames_data:
                    mapped_frames.append(
                        {
                            "frame_number": frame.get("frame_number"),
                            "timestamp": frame.get("timestamp"),
                            "caption": frame.get("analysis"),
                            "detections": [],
                            "points": [],
                            "segmentation": [],
                        }
                    )
                item["objects_data"] = {"frames": mapped_frames, "objects": []}
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="media",
                operation="hydrate_frames_data",
                impact=DegradationImpact.BLOB_HYDRATION,
                exc=exc,
            )

    return item


def get_media_upload_service_instance() -> MediaUploadService:
    blob_service = get_blob_service()
    if not blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    return MediaUploadService(
        blob_service=blob_service,
        db=get_database_service(),
        container_name=get_storage_container_name(),
        dispatch_service_factory=get_video_processing_dispatch_service,
    )


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
    return await service.upload_media(
        file=file,
        user_id=current_user.id,
        preset=preset,
        max_frames=max_frames,
    )


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


@router.get("/media")
async def list_all_media(
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """List all videos/media for the authenticated user with pagination."""
    db = get_database_service()

    try:
        media_list = db.get_media_by_user(current_user.id, limit=limit, offset=offset)

        items = []
        for media in media_list:
            item = media.to_dict()
            # Add additional information
            if item.get("video_metadata", {}) and item["video_metadata"].get("duration"):
                item["duration"] = item["video_metadata"]["duration"]
            if item.get("processing_result", {}) and item["processing_result"].get(
                "frames_analyzed"
            ):
                item["frames_analyzed"] = item["processing_result"]["frames_analyzed"]
            items.append(item)

        return {"total": len(items), "media": items, "limit": limit, "offset": offset}

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
    db = get_database_service()
    blob_service = get_blob_service()

    if not blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    try:
        # Get media from PostgreSQL
        media = db.get_media(media_id)
        if not media:
            raise not_found("Media")

        # Verify ownership
        if media.user_id != current_user.id:
            raise forbidden("You don't have permission to delete this media")

        blob_name = media.blob_name

        # 1. Delete from Blob Storage
        if blob_name:
            try:
                blob_client = blob_service.get_blob_client(
                    container=get_storage_container_name(),
                    blob=blob_name,
                )
                await asyncio.get_running_loop().run_in_executor(None, blob_client.delete_blob)
            except Exception as e:
                logger.warning(f"Error deleting blob: {e}")

        # 2. Delete from Knowledge Graph (Neo4j)
        try:
            kg_service = get_knowledge_graph_service()
            if kg_service:
                kg_service.delete_video_graph(media_id)
        except Exception as e:
            logger.warning(f"Error deleting from graph: {e}")

        # 3. Delete from PostgreSQL
        db.delete_media(media_id)

        return {"message": f"Media {media_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting media {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}")
async def get_media_metadata(media_id: str, current_user: User = Depends(get_current_user)):
    """Get metadata for a multimedia file with signed URL."""
    db = get_database_service()

    try:
        media = db.get_media(media_id)
        if not media:
            raise not_found("Media")

        # Verify ownership
        if media.user_id != current_user.id:
            raise forbidden("You don't have permission to access this media")

        # Update last accessed time for storage tiering
        db.update_media(media_id, {"last_accessed_at": datetime.now(UTC)})

        item = media.to_dict()

        # Add duration from video metadata
        if item.get("video_metadata", {}) and item["video_metadata"].get("duration"):
            item["duration"] = item["video_metadata"]["duration"]

        # Hydrate heavy data from blob storage
        item = await hydrate_data_from_blob(item)

        # Generate URL with SAS token (valid for 1 hour)
        if item.get("blob_name"):
            blob_url = await generate_sas_url(item["blob_name"], expiry_hours=1)
            if blob_url:
                item["blob_url"] = blob_url

        return item

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media lookup failed for {media_id}: {e}", exc_info=True)
        raise internal_error() from e


@router.get("/media/{media_id}/status")
async def get_media_processing_status(
    media_id: str, current_user: User = Depends(get_current_user)
):
    """Get the processing status of a video."""
    db = get_database_service()
    get_media_or_404(media_id, current_user)

    try:
        status = db.get_media_status(media_id)
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
    db = get_database_service()

    try:
        media = db.get_media(media_id)
        if not media:
            raise not_found("Media")

        item = media.to_dict()
        audio_data = item.get("audio_data")

        # Hydrate from blob if necessary
        if item.get("audio_data_blob") and (not audio_data or "transcription" not in audio_data):
            try:
                blob_service = get_blob_service()
                if blob_service:
                    storage_container = get_storage_container_name()
                    blob_client = blob_service.get_blob_client(
                        container=storage_container, blob=item["audio_data_blob"]
                    )
                    audio_json = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: blob_client.download_blob().readall()
                    )
                    audio_data = json.loads(audio_json)
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="hydrate_audio_endpoint_data",
                    impact=DegradationImpact.BLOB_HYDRATION,
                    exc=exc,
                )

        if not audio_data:
            raise not_found(
                "Audio data",
                detail="This video has no audio data or hasn't been processed",
            )

        return {
            "media_id": media_id,
            "audio_data": audio_data,
            "has_transcription": bool(audio_data.get("transcription", {}).get("text")),
            "language": audio_data.get("transcription", {}).get("language"),
            "duration": audio_data.get("transcription", {}).get("duration"),
            "word_count": audio_data.get("stats", {}).get("total_words", 0),
        }

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
    logger.info(f"Search request: media_id={media_id}, query='{query}', top={top}")
    get_media_or_404(media_id, current_user)

    from models.graph_models import NodeType
    from services.graph_search_service import get_graph_search_service

    graph_search = get_graph_search_service()
    graph_resp = await graph_search.hybrid_search(
        query_text=query,
        node_types=[NodeType.FRAME],
        video_id=media_id,
        limit=top,
        use_reranking=False,
    )

    formatted_results = []
    for r in graph_resp.results:
        c = r.content or {}
        formatted_results.append(
            {
                "id": r.node_id,
                "frame_number": int(c.get("frame_number", 0) or 0),
                "timestamp": float(c.get("timestamp", 0.0) or 0.0),
                "content": c.get("description") or "",
                "score": float(r.combined_score or r.vector_score or 0.0),
                "blob_name": "",
                "transcript_text": c.get("transcript_text"),
                "visual_description": c.get("visual_description"),
                "detected_objects": c.get("detected_objects"),
            }
        )

    return {
        "query": query,
        "media_id": media_id,
        "total_results": len(formatted_results),
        "results": formatted_results,
        "source": "knowledge_graph",
    }
