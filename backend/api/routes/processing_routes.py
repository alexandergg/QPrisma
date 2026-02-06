"""
Processing Routes

Handles video processing with FFmpeg, batch processing, and pipeline management.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.dependencies import (
    get_blob_service,
    get_current_user,
    get_storage_container_name,
    get_video_processor,
)
from core.serializers import sanitize_for_json
from models.api_schemas import EnhancedSearchRequest, ProcessingSearchRequest
from models.ffmpeg_config import (
    FFmpegProcessingConfig,
    FrameExtractionConfig,
    ProcessingPreset,
    VideoFilterConfig,
    get_preset_config,
)
from models.user import User
from services.database_service import get_database_service

router = APIRouter(tags=["Processing"])
logger = logging.getLogger(__name__)


def _get_preset_description(preset: ProcessingPreset) -> str:
    """Get description for a preset."""
    descriptions = {
        ProcessingPreset.FAST_PREVIEW: "Fast extraction with low resolution (640x360), ideal for quick previews",
        ProcessingPreset.BALANCED: "Balance between speed and quality (1280x720), 1 FPS, up to 100 frames",
        ProcessingPreset.HIGH_QUALITY: "Maximum quality, 2 FPS, up to 500 frames, slower processing",
        ProcessingPreset.KEYFRAMES_ONLY: "Only video keyframes, useful for main scene changes",
        ProcessingPreset.SCENE_ANALYSIS: "Automatic scene change detection, up to 150 frames",
        ProcessingPreset.TIMELINE_PREVIEW: "30 frames uniformly distributed, low resolution (320x180)",
    }
    return descriptions.get(preset, "No description")


# =============================================================================
# Lazy Initialization
# =============================================================================

_enhanced_search = None


def get_enhanced_search():
    """Get the enhanced search service."""
    global _enhanced_search
    if _enhanced_search is None:
        try:
            from services.enhanced_search import EnhancedSearchService

            _enhanced_search = EnhancedSearchService()
        except Exception as e:
            logger.warning(f"Error initializing Enhanced Search: {e}")
    return _enhanced_search


# =============================================================================
# Background Tasks
# =============================================================================


async def process_video_ffmpeg_background(
    media_id: str,
    blob_name: str,
    config: FFmpegProcessingConfig | None,
    preset: ProcessingPreset | None,
):
    """
    Background task to process video with FFmpeg.
    Includes progress notifications in PostgreSQL.
    """
    processor = get_video_processor()
    db = get_database_service()

    if not processor:
        logger.error(f"Video processor not available for {media_id}")
        return

    def update_processing_status(status: str, message: str, progress: int = 0):
        if db:
            try:
                db.update_media(
                    media_id,
                    {
                        "processing_status": status,
                        "processing_message": message,
                        "processing_progress": float(progress),
                    },
                )
                logger.info(f"Status: {status} - {message}")
            except Exception as e:
                logger.warning(f"Error updating status: {e}")

    try:
        update_processing_status("processing", "Starting FFmpeg processing...", 5)
        logger.info(f"Starting FFmpeg processing for {media_id}")

        update_processing_status("processing", "Extracting frames from video...", 10)

        # Use Batch API (50% cheaper, no rate limits) - always enabled
        result = await processor.process_video_ffmpeg(
            blob_name=blob_name,
            config=config,
            preset=preset,
            process_audio=True,
            audio_language=None,
        )

        frames_count = len(result["frames_data"])

        # Update frames_analyzed in real-time
        if db:
            try:
                db.update_media(
                    media_id,
                    {"processing_result": {"frames_analyzed": frames_count}},
                )
            except Exception as e:
                logger.warning(f"Error updating frames_analyzed: {e}")

        update_processing_status(
            "processing", f"{frames_count} frames analyzed. Saving results...", 70
        )

        logger.info(f"Video processed: {frames_count} frames analyzed")

        update_processing_status("processing", "Finalizing and saving metadata...", 95)

        # Update PostgreSQL with final result
        if db:
            try:
                updates = {
                    "processed": True,
                    "processing_status": "completed",
                    "processing_message": f"✓ Processing completed: {frames_count} frames analyzed",
                    "processing_progress": 100.0,
                    "processing_method": "ffmpeg_optimized",
                    "video_metadata": sanitize_for_json(result["video_metadata"]),
                    "processing_result": sanitize_for_json(result["processing_stats"]),
                }

                # Save heavy data to blob storage
                blob_service = get_blob_service()
                storage_container = get_storage_container_name()

                # 1. Audio Data
                audio_data_clean = sanitize_for_json(result.get("audio_data"))
                if audio_data_clean and blob_service:
                    try:
                        audio_blob_name = f"{media_id}_audio.json"
                        blob_client = blob_service.get_blob_client(
                            container=storage_container, blob=audio_blob_name
                        )
                        blob_client.upload_blob(json.dumps(audio_data_clean), overwrite=True)
                        updates["audio_data_blob"] = audio_blob_name
                        logger.info(f"Audio data saved to blob: {audio_blob_name}")
                    except Exception as e:
                        logger.warning(f"Error saving audio blob: {e}")

                # 2. Frames Data
                frames_data_clean = sanitize_for_json(result.get("frames_data"))
                if frames_data_clean and blob_service:
                    try:
                        # Remove embeddings to save space
                        for frame in frames_data_clean:
                            if "embedding" in frame:
                                del frame["embedding"]

                        frames_blob_name = f"{media_id}_frames.json"
                        blob_client = blob_service.get_blob_client(
                            container=storage_container, blob=frames_blob_name
                        )
                        blob_client.upload_blob(json.dumps(frames_data_clean), overwrite=True)
                        updates["frames_data_blob"] = frames_blob_name
                        logger.info(f"Frames data saved to blob: {frames_blob_name}")
                    except Exception as e:
                        logger.warning(f"Error saving frames blob: {e}")

                db.update_media(media_id, updates)
                logger.info(f"PostgreSQL updated for {media_id}")

            except Exception as e:
                logger.warning(f"Could not update PostgreSQL: {e}")

        logger.info(f"FFmpeg processing completed for {media_id}")

    except Exception as e:
        logger.error(f"Error processing video FFmpeg {media_id}: {e}")
        import traceback

        traceback.print_exc()
        update_processing_status("failed", f"Error in processing: {str(e)[:100]}", 0)


# =============================================================================
# Routes
# =============================================================================


@router.post("/process/video/ffmpeg")
async def process_video_with_ffmpeg(
    background_tasks: BackgroundTasks,
    media_id: str,
    preset: ProcessingPreset | None = None,
    config: FFmpegProcessingConfig | None = None,
    max_frames: int | None = None,
):
    """
    Process a video using FFmpeg with customizable configuration.

    Args:
        media_id: ID of the media in PostgreSQL
        preset: Predefined preset (fast_preview, balanced, high_quality, etc)
        config: Custom FFmpeg configuration (overrides preset)

    Returns:
        Processing information and status
    """
    processor = get_video_processor()
    db = get_database_service()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        # Get video metadata
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        if media.media_type != "video":
            raise HTTPException(status_code=400, detail="The specified media is not a video")

        blob_name = media.blob_name
        if not blob_name:
            raise HTTPException(status_code=404, detail="Blob name not found")

        # Apply max_frames if specified
        final_config = config
        if max_frames and not config:
            preset_config = get_preset_config(preset) if preset else FFmpegProcessingConfig()
            preset_config.frame_extraction.max_frames = max_frames
            final_config = preset_config
        elif max_frames and config:
            config.frame_extraction.max_frames = max_frames
            final_config = config

        # Start background processing
        background_tasks.add_task(
            process_video_ffmpeg_background, media_id, blob_name, final_config, preset
        )

        return {
            "media_id": media_id,
            "message": "FFmpeg processing started in background",
            "preset_used": preset.value if preset else "custom",
            "config": (
                config.dict() if config else get_preset_config(preset).dict() if preset else None
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/process/video/ffmpeg/batch")
async def process_video_with_ffmpeg_batch(
    media_id: str,
    preset: ProcessingPreset | None = None,
    config: FFmpegProcessingConfig | None = None,
    max_frames: int | None = None,
    wait_for_completion: bool = False,
    max_wait_time: int = 3600,
):
    """
    Process a video using FFmpeg with Azure OpenAI Batch API.

    ADVANTAGES vs regular endpoint:
    - 50% cheaper (Batch pricing)
    - No restrictive rate limits
    - Ideal for 100+ frames
    - Real async processing

    DISADVANTAGES:
    - Takes longer (typically 5-10 min)
    - Requires polling for status
    """
    processor = get_video_processor()
    db = get_database_service()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        if media.media_type != "video":
            raise HTTPException(status_code=400, detail="The specified media is not a video")

        blob_name = media.blob_name
        if not blob_name:
            raise HTTPException(status_code=404, detail="Blob name not found")

        # Apply max_frames if specified
        final_config = config
        if max_frames and not config:
            preset_config = get_preset_config(preset) if preset else FFmpegProcessingConfig()
            preset_config.frame_extraction.max_frames = max_frames
            final_config = preset_config
        elif max_frames and config:
            config.frame_extraction.max_frames = max_frames
            final_config = config

        # Process with Batch API (always enabled - 50% cheaper)
        result = await processor.process_video_ffmpeg(
            blob_name=blob_name, config=final_config, preset=preset
        )

        # Update PostgreSQL
        try:
            db.update_media(
                media_id,
                {
                    "processed": True,
                    "processing_method": "ffmpeg_batch",
                    "video_metadata": result["video_metadata"],
                    "processing_result": result["processing_stats"],
                },
            )
        except Exception as e:
            logger.warning(f"Error updating PostgreSQL: {e}")

        return {"media_id": media_id, **result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/batch/status")
async def get_batch_status(batch_id: str):
    """
    Get the status of an Azure OpenAI batch job.

    Returns:
        Batch status: validating, in_progress, finalizing, completed, failed, expired, cancelled
    """
    processor = get_video_processor()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        from services.batch_processor import BatchProcessor

        batch_proc = BatchProcessor(processor.openai_client)
        status = batch_proc.check_batch_status(batch_id)

        return {"batch_id": batch_id, **status}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


@router.post("/batch/cancel")
async def cancel_batch(batch_id: str):
    """Cancel an in-progress batch job."""
    processor = get_video_processor()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        from services.batch_processor import BatchProcessor

        batch_proc = BatchProcessor(processor.openai_client)
        result = batch_proc.cancel_batch(batch_id)

        return {"batch_id": batch_id, "message": "Batch cancelled successfully", "result": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling batch: {str(e)}")


@router.get("/pipeline/preview")
async def get_pipeline_preview(
    preset: ProcessingPreset | None = None,
    extraction_method: str | None = None,
    fps: float | None = None,
    max_frames: int | None = None,
    scale_width: int | None = None,
    scale_height: int | None = None,
):
    """
    Get a preview of the processing pipeline without executing it.
    Useful for frontend visualization.
    """
    processor = get_video_processor()

    if not processor:
        raise HTTPException(status_code=503, detail="Video processor not available")

    try:
        config = None

        if any([extraction_method, fps, max_frames, scale_width, scale_height]):
            from models.ffmpeg_config import FrameExtractionMethod

            frame_config = FrameExtractionConfig()
            if extraction_method:
                frame_config.method = FrameExtractionMethod(extraction_method)
            if fps:
                frame_config.fps = fps
            if max_frames:
                frame_config.max_frames = max_frames

            filter_config = VideoFilterConfig()
            if scale_width:
                filter_config.scale_width = scale_width
            if scale_height:
                filter_config.scale_height = scale_height

            config = FFmpegProcessingConfig(
                frame_extraction=frame_config, video_filters=filter_config
            )
        elif preset:
            config = get_preset_config(preset)

        pipeline = processor.get_processing_pipeline_preview(config=config, preset=preset)

        return pipeline.dict()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/presets")
async def get_available_presets():
    """List all available presets with their descriptions."""
    presets = []

    for preset in ProcessingPreset:
        config = get_preset_config(preset)
        presets.append(
            {
                "name": preset.value,
                "description": _get_preset_description(preset),
                "config": {
                    "extraction_method": config.frame_extraction.method.value,
                    "max_frames": config.frame_extraction.max_frames,
                    "fps": config.frame_extraction.fps,
                    "interval_seconds": config.frame_extraction.interval_seconds,
                    "scale_width": config.video_filters.scale_width,
                    "scale_height": config.video_filters.scale_height,
                },
            }
        )

    return {"presets": presets}


@router.post("/search")
async def search_media(request: ProcessingSearchRequest, current_user: User = Depends(get_current_user)):
    """Global search (Neo4j Knowledge Graph)."""
    try:
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        graph_search = get_graph_search_service()
        resp = await graph_search.hybrid_search(
            query_text=request.query,
            node_types=[NodeType.FRAME],
            video_id=None,
            limit=request.top,
            use_reranking=False,
        )

        results = []
        for r in resp.results:
            c = r.content or {}
            results.append(
                {
                    "id": r.node_id,
                    "media_id": c.get("video_id"),
                    "timestamp": c.get("timestamp"),
                    "frame_number": c.get("frame_number"),
                    "content": c.get("description") or "",
                    "score": float(r.combined_score or r.vector_score or 0.0),
                }
            )

        return {
            "query": request.query,
            "results_count": len(results),
            "results": results,
            "source": "knowledge_graph",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@router.post("/search/enhanced")
async def enhanced_search_endpoint(
    request: EnhancedSearchRequest, current_user: User = Depends(get_current_user)
):
    """
    Enhanced search with re-ranking and intelligent result grouping.

    Features:
    - Query understanding and expansion
    - Hybrid vector + text search
    - LLM-based re-ranking for better relevance
    - Temporal clustering of results
    - Scene-based result grouping
    """
    search_service = get_enhanced_search()

    if not search_service:
        raise HTTPException(status_code=503, detail="Enhanced search not available")

    try:
        result = await search_service.search(
            query=request.query,
            media_id=request.media_id,
            top_k=request.top_k,
            use_reranking=request.use_reranking,
            expand_query=request.expand_query,
        )

        return result.to_dict()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")
