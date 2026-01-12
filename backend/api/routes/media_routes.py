"""
Media Routes

Handles media upload, listing, deletion, and retrieval.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime, timedelta

from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import (
    get_blob_service,
    get_current_user,
    get_video_processor,
)
from models.user import User
from services.database_service import get_database_service

router = APIRouter(tags=["Media"])
logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def generate_sas_url(blob_name: str, expiry_hours: int = 1) -> str | None:
    """Generate a SAS URL for a blob."""
    blob_service = get_blob_service()
    if not blob_service:
        return None

    conn_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    account_key_match = re.search(r"AccountKey=([^;]+)", conn_string)
    account_name_match = re.search(r"AccountName=([^;]+)", conn_string)

    if not (account_key_match and account_name_match):
        return None

    account_key = account_key_match.group(1)
    account_name = account_name_match.group(1)
    container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(UTC) + timedelta(hours=expiry_hours),
    )

    return f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"


def hydrate_data_from_blob(item: dict) -> dict:
    """Hydrate heavy data fields from blob storage."""
    blob_service = get_blob_service()
    if not blob_service:
        return item

    storage_container = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")

    # 1. Hydrate Audio Data
    if item.get("audio_data_blob") and (
        not item.get("audio_data") or "transcription" not in item.get("audio_data", {})
    ):
        try:
            blob_client = blob_service.get_blob_client(
                container=storage_container, blob=item["audio_data_blob"]
            )
            audio_json = blob_client.download_blob().readall()
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
            objects_json = blob_client.download_blob().readall()
            item["objects_data"] = json.loads(objects_json)
        except Exception as e:
            logger.warning(f"Error hydrating objects data: {e}")

    # 3. Hydrate Frames Data
    if item.get("frames_data_blob"):
        try:
            blob_client = blob_service.get_blob_client(
                container=storage_container, blob=item["frames_data_blob"]
            )
            frames_json = blob_client.download_blob().readall()
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
async def upload_media(
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
        raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")

    try:
        # Generate unique ID
        media_id = str(uuid.uuid4())

        # Determine file type
        file_extension = file.filename.split(".")[-1].lower() if file.filename else "bin"
        media_type = "video" if file_extension in ["mp4", "avi", "mov", "mkv", "webm"] else "image"

        # Blob name
        blob_name = f"{media_id}.{file_extension}"

        # Read content
        content = await file.read()

        # Upload to Blob Storage
        container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(content, overwrite=True)

        # Save metadata to PostgreSQL
        media_data = {
            "id": media_id,
            "user_id": current_user.id,
            "blob_name": blob_name,
            "original_filename": file.filename,
            "media_type": media_type,
            "file_size": len(content),
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
                    "max_frames": int(max_frames) if max_frames else 20,
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
                raise HTTPException(status_code=503, detail=f"Celery not available: {e}")

        return {
            "media_id": media_id,
            "blob_name": blob_name,
            "media_type": media_type,
            "file_size": len(content),
            "job_id": job_id,
            "status": media_data.get("processing_status"),
            "message": "File uploaded. Processing queued." if job_id else "File uploaded.",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.post("/upload/optimized")
async def upload_media_optimized(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...),
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
        raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")

    file_extension = file.filename.split(".")[-1].lower() if file.filename else ""
    if file_extension not in ["mp4", "avi", "mov", "mkv", "webm"]:
        raise HTTPException(status_code=400, detail="Only videos (mp4, avi, mov, mkv, webm)")

    try:
        media_id = str(uuid.uuid4())
        blob_name = f"{media_id}.{file_extension}"

        # Read file
        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)
        logger.info(f"File size: {file_size_mb:.2f} MB")

        # Upload to Blob
        container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(content, overwrite=True)

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
            "file_size": len(content),
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
                "max_frames": 20,
                "custom_prompt": None,
                "index_graph": True,
                "preset": None,
                "optimized_pipeline": True,
                "pipeline_config": pipeline_config,
            }
            async_result = process_video_pipeline.apply_async(
                args=[media_id, blob_name, celery_config]
            )
            job_id = async_result.id

            db.update_media(media_id, {"job_id": job_id})

        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Celery not available: {e}")

        return {
            "media_id": media_id,
            "blob_name": blob_name,
            "media_type": "video",
            "file_size": len(content),
            "job_id": job_id,
            "status": "queued" if job_id else "uploaded",
            "message": "Video uploaded. Processing queued.",
            "pipeline": "celery",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/media")
async def list_all_media(current_user: User = Depends(get_current_user)):
    """List all videos/media for the authenticated user."""
    db = get_database_service()

    try:
        media_list = db.get_media_by_user(current_user.id)

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

        return {"total": len(items), "media": items}

    except Exception as e:
        logger.error(f"Error listing media: {e}")
        return {"total": 0, "media": []}


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
        raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")

    try:
        # Get media from PostgreSQL
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        # Verify ownership
        if media.user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="You don't have permission to delete this media"
            )

        blob_name = media.blob_name

        # 1. Delete from Blob Storage
        if blob_name and video_processor:
            try:
                video_processor.delete_video(blob_name)
            except Exception as e:
                logger.warning(f"Error deleting blob: {e}")

        # 2. Delete from Knowledge Graph (Neo4j)
        try:
            from services.knowledge_graph import KnowledgeGraphService

            KnowledgeGraphService().delete_video_graph(media_id)
        except Exception as e:
            logger.warning(f"Error deleting from graph: {e}")

        # 3. Delete from PostgreSQL
        db.delete_media(media_id)

        return {"message": f"Media {media_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting media: {str(e)}")


@router.get("/media/{media_id}")
async def get_media_metadata(media_id: str, current_user: User = Depends(get_current_user)):
    """Get metadata for a multimedia file with signed URL."""
    db = get_database_service()

    try:
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        # Verify ownership
        if media.user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="You don't have permission to access this media"
            )

        item = media.to_dict()

        # Add duration from video metadata
        if item.get("video_metadata", {}) and item["video_metadata"].get("duration"):
            item["duration"] = item["video_metadata"]["duration"]

        # Hydrate heavy data from blob storage
        item = hydrate_data_from_blob(item)

        # Generate URL with SAS token (valid for 1 hour)
        if item.get("blob_name"):
            blob_url = generate_sas_url(item["blob_name"], expiry_hours=1)
            if blob_url:
                item["blob_url"] = blob_url

        return item

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Media not found: {str(e)}")


@router.get("/media/{media_id}/status")
async def get_media_processing_status(media_id: str):
    """Get the processing status of a video."""
    db = get_database_service()

    try:
        status = db.get_media_status(media_id)
        if not status:
            raise HTTPException(status_code=404, detail="Media not found")
        return status

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Media not found: {str(e)}")


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
            raise HTTPException(status_code=404, detail="Media not found")

        item = media.to_dict()
        audio_data = item.get("audio_data")

        # Hydrate from blob if necessary
        if item.get("audio_data_blob") and (not audio_data or "transcription" not in audio_data):
            try:
                blob_service = get_blob_service()
                if blob_service:
                    storage_container = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")
                    blob_client = blob_service.get_blob_client(
                        container=storage_container, blob=item["audio_data_blob"]
                    )
                    audio_json = blob_client.download_blob().readall()
                    audio_data = json.loads(audio_json)
            except Exception as e:
                logger.warning(f"Error hydrating audio data: {e}")

        if not audio_data:
            raise HTTPException(
                status_code=404, detail="This video has no audio data or hasn't been processed"
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
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/media/{media_id}/search")
async def search_in_video(
    media_id: str, query: str, top: int = 10, current_user: User = Depends(get_current_user)
):
    """
    Semantic search within a specific video.
    Returns relevant frames with timestamps.
    """
    logger.info(f"Search request: media_id={media_id}, query='{query}', top={top}")

    from models.graph_models import NodeType
    from services.graph_search_service import get_graph_search_service

    graph_search = get_graph_search_service()
    graph_resp = graph_search.hybrid_search(
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
                "blob_name": c.get("image_url") or "",
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
