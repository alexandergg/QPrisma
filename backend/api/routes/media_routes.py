"""
Media Routes

Handles media upload, listing, deletion, and retrieval.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial

from azure.storage.blob import BlobSasPermissions, generate_blob_sas
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
    get_blob_service,
    get_current_user,
    get_knowledge_graph_service,
    get_media_or_404,
    get_storage_account_info,
    get_storage_container_name,
    get_video_processor,
)
from api.rate_limit import limiter
from core.errors import bad_request, forbidden, not_found, service_unavailable
from core.exceptions import internal_error
from models.user import User
from services.database_service import get_database_service

router = APIRouter(tags=["Media"])
logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def generate_sas_url(blob_name: str, expiry_hours: int = 1) -> str | None:
    """Generate a SAS URL for reading a blob."""
    account_info = get_storage_account_info()
    if not account_info:
        return None

    account_name, account_key, container_name = account_info

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(UTC) + timedelta(hours=expiry_hours),
    )

    return f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"


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
        except Exception as e:
            logger.warning(f"Error hydrating audio data: {e}")

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
        except Exception as e:
            logger.warning(f"Error hydrating objects data: {e}")

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
        except Exception as e:
            logger.warning(f"Error hydrating frames data: {e}")

    return item


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
    blob_service = get_blob_service()
    db = get_database_service()

    if not blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    try:
        # Generate unique ID
        media_id = str(uuid.uuid4())

        # Determine file type
        file_extension = file.filename.split(".")[-1].lower() if file.filename else "bin"
        media_type = "video" if file_extension in ["mp4", "avi", "mov", "mkv", "webm"] else "image"

        # Blob name
        blob_name = f"{media_id}.{file_extension}"

        # Stream upload to Blob Storage (avoids loading entire file into memory)
        container_name = get_storage_container_name()
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
        file_size = file.size or 0
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(blob_client.upload_blob, file.file, overwrite=True, length=file_size or None),
        )

        # Get actual size from blob if not known from the upload
        if not file_size:
            props = await loop.run_in_executor(None, blob_client.get_blob_properties)
            file_size = props.size

        # Save metadata to PostgreSQL
        media_data = {
            "id": media_id,
            "user_id": current_user.id,
            "blob_name": blob_name,
            "original_filename": file.filename,
            "media_type": media_type,
            "file_size": file_size,
            "content_type": file.content_type,
            "processing_status": "queued" if media_type == "video" else "uploaded",
        }

        db.create_media(media_data)

        # Queue in Celery
        job_id = None
        if media_type == "video":
            try:
                from tasks.video_tasks import process_video_pipeline

                celery_config = {
                    "max_frames": int(max_frames) if max_frames else None,
                    "custom_prompt": None,
                    "index_graph": True,
                    "preset": preset,
                }
                async_result = process_video_pipeline.apply_async(
                    args=[media_id, blob_name, celery_config]
                )
                job_id = async_result.id

                # Update with job_id
                db.update_media(media_id, {"job_id": job_id})

            except Exception as e:
                logger.error(f"Celery dispatch failed for {media_id}: {e}", exc_info=True)
                raise service_unavailable("Task queue is unavailable") from e

        return {
            "media_id": media_id,
            "blob_name": blob_name,
            "media_type": media_type,
            "file_size": file_size,
            "job_id": job_id,
            "status": media_data.get("processing_status"),
            "message": "File uploaded. Processing queued." if job_id else "File uploaded.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        raise internal_error() from e


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

    blob_service = get_blob_service()
    db = get_database_service()

    if not blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    file_extension = file.filename.split(".")[-1].lower() if file.filename else ""
    if file_extension not in ["mp4", "avi", "mov", "mkv", "webm"]:
        raise bad_request("Only videos (mp4, avi, mov, mkv, webm)")

    try:
        media_id = str(uuid.uuid4())
        blob_name = f"{media_id}.{file_extension}"

        # Stream upload to Blob (avoids loading entire file into memory)
        container_name = get_storage_container_name()
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
        file_size = file.size or 0
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(blob_client.upload_blob, file.file, overwrite=True, length=file_size or None),
        )

        # Get actual size from blob if not known
        if not file_size:
            props = await loop.run_in_executor(None, blob_client.get_blob_properties)
            file_size = props.size

        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"File size: {file_size_mb:.2f} MB")

        # Save to PostgreSQL
        pipeline_config = {
            "use_scene_detection": use_scene_detection,
            "use_hierarchical_summary": use_hierarchical_summary,
            "scene_threshold": scene_threshold,
            "max_scenes_per_chapter": max_scenes_per_chapter,
        }

        media_data = {
            "id": media_id,
            "user_id": current_user.id,
            "blob_name": blob_name,
            "original_filename": file.filename,
            "media_type": "video",
            "file_size": file_size,
            "content_type": file.content_type,
            "processing_status": "queued",
            "optimized_pipeline": True,
            "pipeline_config": pipeline_config,
        }

        db.create_media(media_data)

        # Queue in Celery
        job_id = None
        try:
            from tasks.video_tasks import process_video_pipeline

            celery_config = {
                "max_frames": min(max_frames, 500),  # User-configurable, capped at 500
                "custom_prompt": None,
                "index_graph": True,
                "preset": preset,
                "optimized_pipeline": True,
                "pipeline_config": pipeline_config,
            }
            async_result = process_video_pipeline.apply_async(
                args=[media_id, blob_name, celery_config]
            )
            job_id = async_result.id

            db.update_media(media_id, {"job_id": job_id})

        except Exception as e:
            logger.error(f"Celery dispatch failed for {media_id}: {e}", exc_info=True)
            raise service_unavailable("Task queue is unavailable") from e

        return {
            "media_id": media_id,
            "blob_name": blob_name,
            "media_type": "video",
            "file_size": file_size,
            "job_id": job_id,
            "status": "queued" if job_id else "uploaded",
            "message": "Video uploaded. Processing queued.",
            "pipeline": "celery",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise internal_error() from e


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
    video_processor = get_video_processor()

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
        if blob_name and video_processor:
            try:
                video_processor.delete_video(blob_name)
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
            blob_url = generate_sas_url(item["blob_name"], expiry_hours=1)
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
            except Exception as e:
                logger.warning(f"Error hydrating audio data: {e}")

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
