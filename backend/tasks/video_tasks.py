"""
Video Processing Tasks for Celery

Asynchronous tasks for video processing in QPrisma.

Pipeline Flow:
    1. process_video_pipeline (orchestrator)
       ├── download_video_task
       ├── extract_frames_task
       ├── analyze_frames_task (parallel)
       ├── generate_embeddings_task (batch)
       ├── transcribe_audio_task
       ├── index_to_neo4j (Knowledge Graph)
       ├── index_transcription_to_graph
       ├── entity_extraction (from frame descriptions)
       └── cleanup_task

Usage:
    from tasks.video_tasks import process_video_pipeline

    # Start processing
    result = process_video_pipeline.delay(
        video_id="abc123",
        blob_name="videos/my_video.mp4",
        config={"max_frames": 20}
    )

    # Get task_id for tracking
    task_id = result.id

    # Check status
    from tasks.celery_app import celery_app
    status = celery_app.AsyncResult(task_id)
    status.state  # PENDING, STARTED, SUCCESS, FAILURE
    status.info   # Progress metadata
"""

import asyncio
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure path
backend_path = str(Path(__file__).parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)


# Logging
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Lazy Loading of Services (avoid heavy imports at module load time)
# =============================================================================

_services_initialized = False
_blob_service = None
_openai_client = None
_video_processor = None
_cached_processor = None
_cache_service = None
_db_service = None


def _initialize_services():
    """Initialize Azure services (lazy loading)."""
    global _services_initialized, _blob_service, _openai_client
    global _video_processor, _cache_service, _db_service

    if _services_initialized:
        return

    from dotenv import load_dotenv

    load_dotenv()

    from azure.storage.blob import BlobServiceClient
    from openai import AsyncAzureOpenAI

    from core.config import settings

    # Azure Blob storage
    if settings.azure.storage_connection_string:
        _blob_service = BlobServiceClient.from_connection_string(
            settings.azure.storage_connection_string
        )

    # Azure OpenAI (async for non-blocking pipeline)
    if settings.azure.is_openai_configured:
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure.openai_endpoint,
            api_key=settings.azure.openai_api_key,
            api_version=settings.azure.openai_api_version,
        )

    # Video Processor
    if _blob_service and _openai_client:
        from services.video_processor import VideoProcessor

        _video_processor = VideoProcessor(
            openai_client=_openai_client,
            blob_service=_blob_service,
            container_name=settings.azure.storage_container_name,
        )

    # PostgreSQL Database Service (replaces Cosmos DB)
    from services.database_service import get_database_service

    _db_service = get_database_service()

    _services_initialized = True
    logger.info("Services initialized for Celery worker")


async def _get_cache_service():
    """Get the cache service (async)."""
    global _cache_service
    if _cache_service is None:
        from services.cache_service import CacheService

        _cache_service = CacheService()
        await _cache_service.connect()
    return _cache_service


# =============================================================================
# Low-Level Tasks
# =============================================================================


@celery_app.task(
    bind=True, name="tasks.video_tasks.update_job_status", max_retries=3, default_retry_delay=5
)
def update_job_status(
    self,
    job_id: str,
    status: str,
    progress: int,
    stage: str,
    message: str | None = None,
    error: str | None = None,
    result_data: dict | None = None,
):
    """
    Update job status in cache and notify via Redis Pub/Sub.
    This task is used to notify progress to clients in real time.

    Uses synchronous Redis to avoid event loop issues in Celery.
    """
    import json

    import redis

    from core.config import settings

    try:
        redis_client = redis.from_url(settings.redis.url)

        # 1. Save job status in Redis (cache)
        status_data = {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "stage": stage,
            "message": message,
            "error": error,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        if result_data:
            status_data["result"] = result_data

        # Save in Redis with 1 hour TTL
        cache_key = f"job_status:{job_id}"
        redis_client.setex(cache_key, 3600, json.dumps(status_data))

        logger.info(f"Job {job_id}: {status} ({progress}%) - {stage}")

        # 2. Publish event to Redis Pub/Sub for WebSockets
        if status == "completed":
            event_type = "completed"
            event_data = {"result": result_data}
        elif status == "failed":
            event_type = "failed"
            event_data = {"error": error}
        else:
            event_type = "progress"
            event_data = {"progress": progress, "stage": stage, "message": message}

        pubsub_message = json.dumps({"type": event_type, "job_id": job_id, "data": event_data})

        redis_client.publish("qprisma:websocket:events", pubsub_message)
        logger.debug(f"Published WebSocket event for job {job_id}: {event_type}")

        redis_client.close()

    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        # Don't fail the task, just log

    return {"job_id": job_id, "status": status}


@celery_app.task(
    bind=True, name="tasks.video_tasks.download_video_task", max_retries=3, default_retry_delay=30
)
def download_video_task(self, blob_name: str, job_id: str) -> dict:
    """
    Download a video from Azure Blob Storage to a temporary file.

    Returns:
        Dict with temp_path of the downloaded file.
    """
    _initialize_services()

    try:
        update_job_status.delay(job_id, "processing", 5, "downloading", "Downloading video...")

        # Create temporary file
        suffix = Path(blob_name).suffix or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_path = tmp_file.name

        # Download
        from core.config import settings

        blob_client = _blob_service.get_blob_client(
            container=settings.azure.storage_container_name, blob=blob_name
        )

        with open(tmp_path, "wb") as f:
            stream = blob_client.download_blob()
            for chunk in stream.chunks():
                f.write(chunk)

        file_size = os.path.getsize(tmp_path)
        logger.info(f"Downloaded {blob_name} ({file_size} bytes) to {tmp_path}")

        return {"temp_path": tmp_path, "blob_name": blob_name, "file_size": file_size}

    except Exception as e:
        logger.error(f"Download failed: {e}")
        update_job_status.delay(job_id, "failed", 0, "download_error", str(e), str(e))
        raise self.retry(exc=e) from e


@celery_app.task(bind=True, name="tasks.video_tasks.extract_frames_task", max_retries=2)
def extract_frames_task(
    self,
    download_result: dict,
    job_id: str,
    max_frames: int | None = None,
    preset: str | None = None,
) -> dict:
    """
    Extract frames from a video using FFmpegVideoProcessor (PyAV + deduplication).

    Uses the optimized :class:`FFmpegVideoProcessor` for frame extraction and
    PIL/Pillow for re-encoding frames into the configured format (WebP by default).

    When a *preset* is provided, the corresponding
    :func:`get_preset_config` configuration is used (honouring the
    extraction method, interval, scene threshold, etc.).  Otherwise
    falls back to ``UNIFORM`` distribution with *max_frames*.

    Returns:
        Dict with list of frames (bytes) and metadata.
    """
    _initialize_services()
    import io

    from PIL import Image, ImageFilter

    from core.config import settings
    from models.ffmpeg_config import (
        FFmpegProcessingConfig,
        FrameExtractionConfig,
        FrameExtractionMethod,
        ProcessingPreset,
        get_preset_config,
    )
    from services.ffmpeg_processor import FFmpegVideoProcessor

    # ---- helpers for quality metrics (PIL-based, no cv2) --------------------

    def calculate_blur_score(image_data: bytes) -> float:
        """Approximate blur using edge-intensity variance. Higher = sharper."""
        try:
            img = Image.open(io.BytesIO(image_data)).convert("L")
            # Laplacian-like edge detection via FIND_EDGES kernel
            edges = img.filter(ImageFilter.FIND_EDGES)
            import numpy as np

            arr = np.asarray(edges, dtype=np.float64)
            variance = float(arr.var())
            # Normalize to 0-1 (empirical cap at 2000 for edge filter)
            return min(variance / 2000.0, 1.0)
        except Exception:
            return 0.0

    def calculate_brightness(image_data: bytes) -> float:
        """Calculate average brightness. 0=dark, 1=bright."""
        try:
            img = Image.open(io.BytesIO(image_data)).convert("L")
            import numpy as np

            arr = np.asarray(img, dtype=np.float64)
            return float(arr.mean() / 255.0)
        except Exception:
            return 0.0

    def encode_frame(image_data: bytes, fmt: str = "webp", quality: int = 80) -> bytes:
        """Re-encode raw frame bytes into the target format for Vision API."""
        img = Image.open(io.BytesIO(image_data))
        buf = io.BytesIO()
        pil_format = fmt.upper() if fmt.lower() != "webp" else "WEBP"
        img.save(buf, format=pil_format, quality=quality)
        return buf.getvalue()

    # ---- main logic ---------------------------------------------------------

    try:
        update_job_status.delay(
            job_id, "processing", 15, "extracting", f"Extracting up to {max_frames} frames..."
        )

        temp_path = download_result["temp_path"]

        # Read settings for decoder and encoding
        decoder_backend = settings.app.video_decoder_backend
        encoding_format = settings.processing.frame_encoding_format
        encoding_quality = settings.processing.frame_encoding_quality

        # Build FFmpeg processor config from preset (if provided) or defaults
        if preset:
            try:
                preset_enum = ProcessingPreset(preset)
                config = get_preset_config(preset_enum)
                # Override max_frames only if explicitly provided by the caller
                if max_frames is not None:
                    config.frame_extraction.max_frames = max_frames
            except ValueError:
                logger.warning("Unknown preset '%s' — falling back to UNIFORM", preset)
                config = FFmpegProcessingConfig(
                    frame_extraction=FrameExtractionConfig(
                        method=FrameExtractionMethod.UNIFORM,
                        max_frames=max_frames or settings.app.default_max_frames,
                    )
                )
        else:
            config = FFmpegProcessingConfig(
                frame_extraction=FrameExtractionConfig(
                    method=FrameExtractionMethod.UNIFORM,
                    max_frames=max_frames or settings.app.default_max_frames,
                )
            )

        # Ensure decoder backend and deduplication are always applied
        config.frame_extraction.decoder_backend = decoder_backend
        config.frame_extraction.deduplication_enabled = True
        config.frame_extraction.deduplication_threshold = 12

        processor = FFmpegVideoProcessor(config=config)

        # Get video metadata via ffprobe
        video_info = processor.get_video_info(temp_path)
        fps = video_info.get("fps", 0)
        total_frames = video_info.get("frame_count", 0)
        duration = video_info.get("duration", 0)
        width = video_info.get("width", 0)
        height = video_info.get("height", 0)

        # Extract frames (returns list of dicts with image_data bytes)
        raw_frames = processor.extract_frames_ffmpeg(temp_path, return_as_bytes=True)
        frames_before_dedup = getattr(processor.status, "frames_extracted", len(raw_frames))
        # The processor already applies deduplication internally when enabled,
        # so raw_frames is the post-dedup list.  We capture pre-dedup count
        # from the processor status which is updated before dedup runs.

        # Re-encode each frame and compute quality metrics
        frames_data = []
        for idx, raw in enumerate(raw_frames):
            raw_image = raw.get("image_data", b"")

            # Re-encode into configured format (webp/jpeg)
            encoded_bytes = encode_frame(raw_image, fmt=encoding_format, quality=encoding_quality)

            # Quality metrics (computed on the raw extraction, before re-encode)
            blur_score = calculate_blur_score(raw_image)
            brightness = calculate_brightness(raw_image)

            frames_data.append(
                {
                    "index": idx,
                    "frame_number": raw.get("frame_number", idx),
                    "timestamp": round(raw.get("timestamp", 0.0), 2),
                    "image_bytes": encoded_bytes,
                    "blur_score": round(blur_score, 4),
                    "brightness": round(brightness, 4),
                }
            )

        logger.info(
            "Extracted %d frames from %s (decoder=%s, format=%s, dedup=%s)",
            len(frames_data),
            temp_path,
            decoder_backend,
            encoding_format,
            config.frame_extraction.deduplication_enabled,
        )

        return {
            "frames": frames_data,
            "metadata": {
                "fps": fps,
                "total_frames": total_frames,
                "duration": round(duration, 2),
                "resolution": f"{width}x{height}",
                "frames_extracted": len(frames_data),
                "decoder_backend": decoder_backend,
                "deduplication_enabled": config.frame_extraction.deduplication_enabled,
                "frames_before_dedup": frames_before_dedup,
                "encoding_format": encoding_format,
            },
            "temp_path": temp_path,
            "blob_name": download_result["blob_name"],
        }

    except Exception as e:
        logger.error(f"Frame extraction failed: {e}")
        update_job_status.delay(job_id, "failed", 15, "extraction_error", str(e), str(e))
        raise


@celery_app.task(
    bind=True,
    name="tasks.video_tasks.analyze_frame_task",
    max_retries=3,
    default_retry_delay=60,
    rate_limit="30/m",  # Max 30 per minute (protect Azure OpenAI)
)
def analyze_frame_task(
    self, frame_data: dict, job_id: str, custom_prompt: str | None = None
) -> dict:
    """
    Analyze an individual frame with GPT-4V.
    Rate limited to protect Azure OpenAI quota.

    Accepts frames encoded as WebP or JPEG bytes (produced by
    ``extract_frames_task``).  The raw image bytes are passed directly
    to ``analyze_frame_with_gpt4v`` — no cv2/numpy round-trip required.
    """
    _initialize_services()
    import base64

    try:
        # Decode frame bytes (may arrive as base64 str from JSON serialization)
        frame_bytes = (
            base64.b64decode(frame_data["image_bytes"])
            if isinstance(frame_data["image_bytes"], str)
            else frame_data["image_bytes"]
        )

        # Pass raw image bytes directly — _encode_frame_optimized handles bytes
        analysis = asyncio.run(
            _video_processor.analyze_frame_with_gpt4v(
                frame_bytes,
                custom_prompt=custom_prompt,
                timestamp=frame_data.get("timestamp"),
            )
        )

        return {
            "index": frame_data["index"],
            "frame_number": frame_data.get("frame_number"),
            "timestamp": frame_data["timestamp"],
            "analysis": analysis.get("analysis"),
            "tokens_used": analysis.get("tokens_used", 0),
            "error": analysis.get("error"),
        }

    except Exception as e:
        logger.error(f"Frame analysis failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return {
            "index": frame_data.get("index", -1),
            "timestamp": frame_data.get("timestamp", 0),
            "analysis": None,
            "error": str(e),
        }


@celery_app.task(
    bind=True, name="tasks.video_tasks.generate_embedding_task", max_retries=3, rate_limit="60/m"
)
def generate_embedding_task(self, text: str) -> list[float]:
    """Generate embedding for a text."""
    _initialize_services()

    if not text or not text.strip():
        return []

    try:
        return asyncio.run(_video_processor.generate_embedding(text))
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        return []


@celery_app.task(bind=True, name="tasks.video_tasks.generate_embeddings_batch_task", max_retries=2)
def generate_embeddings_batch_task(self, texts: list[str], job_id: str) -> list[list[float]]:
    """Generate embeddings in batch."""
    _initialize_services()

    try:
        update_job_status.delay(
            job_id, "processing", 75, "embeddings", f"Generating {len(texts)} embeddings..."
        )

        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        embeddings = asyncio.run(
            _video_processor.generate_embeddings_batch(valid_texts, batch_size=16)
        )
        logger.info(f"Generated {len(embeddings)} embeddings")

        return embeddings

    except Exception as e:
        logger.error(f"Batch embedding failed: {e}")
        raise


@celery_app.task(bind=True, name="tasks.video_tasks.transcribe_audio_task", max_retries=2)
def transcribe_audio_task(self, temp_path: str, job_id: str) -> dict:
    """Transcribe video audio with Whisper.

    Performs the full audio pipeline (extract → transcribe → analyse) with
    granular progress updates sent via :func:`update_job_status`.  The Whisper
    backend (``azure`` or ``faster_whisper``) is read from
    ``settings.azure.whisper_backend``.
    """
    _initialize_services()

    from core.config import settings

    whisper_backend = settings.azure.whisper_backend
    logger.info(
        "transcribe_audio_task started – backend=%s, path=%s",
        whisper_backend,
        temp_path,
    )

    try:
        # --- resolve an AudioProcessor instance ---
        audio_proc = None
        if _video_processor and _video_processor.audio_processor:
            audio_proc = _video_processor.audio_processor
        elif _openai_client:
            logger.info("VideoProcessor unavailable, creating standalone AudioProcessor")
            from services.audio_processor import AudioProcessor

            audio_proc = AudioProcessor(
                _openai_client,
                rate_limit_rpm=settings.azure.openai_whisper_rpm,
            )

        if audio_proc is None:
            logger.warning("No AudioProcessor available (no OpenAI client)")
            return {
                "transcription": None,
                "success": False,
                "error": "Audio processor not available",
                "whisper_backend": whisper_backend,
                "chunked": False,
                "chunk_count": 0,
                "parallel_transcription": False,
            }

        # 1. Extract audio
        update_job_status.delay(job_id, "processing", 55, "transcribing", "Extracting audio...")
        audio_path = audio_proc.extract_audio_from_video(temp_path)

        # 2. Transcribe
        backend_label = (
            "faster-whisper (local)" if whisper_backend == "faster_whisper" else "Azure Whisper API"
        )
        update_job_status.delay(
            job_id,
            "processing",
            60,
            "transcribing",
            f"Transcribing with {backend_label}...",
        )
        transcription = asyncio.run(audio_proc.transcribe_audio(audio_path))

        chunked = transcription.get("chunked", False)
        chunk_count = transcription.get("chunk_count", 1 if not chunked else 0)
        parallel = chunked  # parallel transcription is used when chunking

        logger.info(
            "Transcription complete – backend=%s, chunked=%s, chunks=%d",
            whisper_backend,
            chunked,
            chunk_count,
        )

        # 3. Analyse transcription with GPT
        full_text = transcription.get("text", "")
        analysis: dict = {}

        if full_text and len(full_text.strip()) > 50:
            update_job_status.delay(
                job_id,
                "processing",
                70,
                "transcribing",
                "Analyzing transcription...",
            )
            analysis = asyncio.run(audio_proc.analyze_transcription(full_text))
        else:
            logger.warning("Transcription too short or empty, skipping analysis")

        # 4. Build result (preserves original return shape)
        transcription_data = {
            "text": full_text,
            "language": transcription.get("language"),
            "duration": transcription.get("duration"),
            "segments": transcription.get("segments", []),
            "words": transcription.get("words", []),
        }

        return {
            "transcription": transcription_data,
            "analysis": analysis,
            "success": True,
            "error": None,
            "whisper_backend": whisper_backend,
            "chunked": chunked,
            "chunk_count": chunk_count,
            "parallel_transcription": parallel,
        }

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return {
            "transcription": None,
            "success": False,
            "error": str(e),
            "whisper_backend": whisper_backend,
            "chunked": False,
            "chunk_count": 0,
            "parallel_transcription": False,
        }


@celery_app.task(bind=True, name="tasks.video_tasks.cleanup_task")
def cleanup_task(self, temp_path: str):
    """Clean up temporary files."""
    try:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
            logger.info(f"Cleaned up: {temp_path}")
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


@celery_app.task(bind=True, name="tasks.video_tasks.index_transcription_to_graph", max_retries=3)
def index_transcription_to_graph(
    self, video_id: str, transcription_data: dict, job_id: str
) -> dict:
    """
    Index transcription segments to Neo4j Knowledge Graph.

    Args:
        video_id: Video ID.
        transcription_data: Transcription data with segments.
        job_id: Job ID for status updates.

    Returns:
        Dict with indexing statistics.
    """
    _initialize_services()

    try:
        from models.graph_models import AudioSegmentNode
        from services.knowledge_graph import get_knowledge_graph_service

        graph = get_knowledge_graph_service()

        # Ensure Neo4j connection
        if not graph.is_connected:
            graph.connect()

        # Get transcription segments
        segments = transcription_data.get("segments", [])
        if not segments:
            logger.info(f"No transcript segments to index for video {video_id}")
            return {"indexed": 0, "success": True, "message": "No segments to index"}

        logger.info(f"Starting transcript indexing: {len(segments)} segments for video {video_id}")

        # Delete existing transcriptions for this video
        try:
            deleted = graph.delete_video_transcripts(video_id)
            if deleted > 0:
                logger.info(f"Deleted {deleted} existing transcript segments for video {video_id}")
        except Exception as e:
            logger.warning(f"Could not delete existing transcripts: {e}")

        # Create AudioSegment nodes
        language = transcription_data.get("language", "unknown")
        audio_segments = []

        for idx, segment in enumerate(segments):
            segment_node = AudioSegmentNode(
                id=f"{video_id}_audio_{idx}",  # Use index to avoid duplicate IDs
                video_id=video_id,
                start_time=segment.get("start", 0),
                end_time=segment.get("end", 0),
                text=segment.get("text", "").strip(),
                language=language,
                confidence=segment.get("avg_logprob", 0) if segment.get("avg_logprob") else 0.9,
            )
            audio_segments.append(segment_node)

        # Index in batch (with internal batch handling)
        created = graph.create_audio_segments_batch(audio_segments)

        success = created > 0 or len(segments) == 0

        if created < len(segments) * 0.5:  # Less than 50% indexed
            logger.error(
                f"Transcript indexing partial failure: only {created}/{len(segments)} segments indexed"
            )

        logger.info(f"Indexed {created}/{len(segments)} transcript segments for video {video_id}")

        return {
            "indexed": created,
            "total_segments": len(segments),
            "language": language,
            "success": success,
            "error": None if success else f"Only indexed {created}/{len(segments)} segments",
        }

    except Exception as e:
        error_msg = f"Failed to index transcription for video {video_id}: {e}"
        logger.error(error_msg, exc_info=True)

        # Retry if it's a connection error
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            try:
                self.retry(countdown=5, exc=e)
            except Exception:
                pass  # Max retries reached

        return {"indexed": 0, "success": False, "error": str(e)}


# =============================================================================
# Main Pipeline
# =============================================================================


@celery_app.task(bind=True, name="tasks.video_tasks.process_video_pipeline", max_retries=1)
def process_video_pipeline(self, video_id: str, blob_name: str, config: dict | None = None) -> dict:
    """
    Complete video processing pipeline.

    This is the main orchestrator that coordinates all sub-tasks.

    Args:
        video_id: Unique video ID.
        blob_name: Blob name in Azure Storage.
        config: Optional configuration (max_frames, custom_prompt, etc.).

    Returns:
        Dict with complete processing results.
    """
    _initialize_services()

    job_id = self.request.id or f"job_{video_id}"
    config = config or {}
    max_frames = config.get("max_frames")
    custom_prompt = config.get("custom_prompt")
    preset = config.get("preset")

    start_time = time.time()

    try:
        # 1. Start job
        update_job_status(job_id, "processing", 0, "started", f"Starting processing of {blob_name}")

        # 2. Download video
        download_result = download_video_task(blob_name, job_id)
        temp_path = download_result["temp_path"]

        # 3. Extract frames
        extraction_result = extract_frames_task(download_result, job_id, max_frames, preset=preset)
        frames = extraction_result["frames"]
        metadata = extraction_result["metadata"]

        # 4. Analyze frames with Batch API (50% cheaper)
        update_job_status(
            job_id,
            "processing",
            25,
            "analyzing",
            f"Analyzing {len(frames)} frames with Batch API...",
        )

        frame_analyses = []
        try:
            # Use Batch API for frame analysis (50% savings)
            import base64

            from services.batch_processor import BatchProcessor

            batch_proc = BatchProcessor(_video_processor.openai_client)

            # Prepare frames for Batch API
            frames_for_batch = []
            for frame_data in frames:
                image_bytes = frame_data.get("image_bytes", b"")
                if isinstance(image_bytes, bytes):
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                else:
                    image_base64 = image_bytes

                frames_for_batch.append(
                    {
                        "frame_number": frame_data.get("frame_number", frame_data.get("index", 0)),
                        "timestamp": frame_data.get("timestamp", 0),
                        "image_base64": image_base64,
                    }
                )

            # Submit batch job
            update_job_status(
                job_id,
                "processing",
                30,
                "batch_submit",
                f"Submitting {len(frames)} frames to Batch API...",
            )
            vision_requests = batch_proc.create_vision_batch_requests(
                frames_for_batch, custom_prompt
            )
            vision_batch_id = asyncio.run(
                batch_proc.submit_batch_job(
                    vision_requests, description=f"Celery: {blob_name} ({len(frames)} frames)"
                )
            )
            logger.info(f"Batch job created: {vision_batch_id}")

            # Wait for completion
            update_job_status(
                job_id,
                "processing",
                35,
                "batch_wait",
                "Waiting for Batch API (typically 3-5 min)...",
            )
            success = asyncio.run(
                batch_proc.wait_for_batch_completion(
                    vision_batch_id, check_interval=30, max_wait_time=1800
                )
            )

            if not success:
                raise Exception(f"Batch job timeout or failed: {vision_batch_id}")

            # Get results
            update_job_status(
                job_id, "processing", 55, "batch_results", "Processing Batch API results..."
            )
            vision_results = asyncio.run(batch_proc.get_batch_results(vision_batch_id))
            parsed_analyses = batch_proc.parse_vision_results(vision_results)

            # Convert to expected format
            for i, frame_data in enumerate(frames):
                frame_id = f"frame_{frame_data.get('frame_number', i)}"
                analysis_text = parsed_analyses.get(frame_id, {}).get("analysis", "")
                frame_analyses.append(
                    {
                        "index": i,
                        "frame_number": frame_data.get("frame_number", i),
                        "timestamp": frame_data.get("timestamp", 0),
                        "analysis": analysis_text,
                        "tokens_used": 0,
                        "blur_score": frame_data.get("blur_score", 0.0),
                        "brightness": frame_data.get("brightness", 0.0),
                    }
                )

            logger.info(f"Batch API completed: {len(frame_analyses)} frames analyzed")

        except Exception as batch_error:
            logger.warning(f"Batch API failed, falling back to individual calls: {batch_error}")
            # Fallback: sequential analysis (more expensive but works)
            import base64

            for i, frame_data in enumerate(frames):
                progress = 25 + int((i / len(frames)) * 35)
                update_job_status(
                    job_id,
                    "processing",
                    progress,
                    "analyzing",
                    f"Analyzing frame {i+1}/{len(frames)} (fallback)",
                )

                frame_data_copy = frame_data.copy()
                if isinstance(frame_data_copy.get("image_bytes"), bytes):
                    frame_data_copy["image_bytes"] = base64.b64encode(
                        frame_data_copy["image_bytes"]
                    ).decode()

                analysis = analyze_frame_task(frame_data_copy, job_id, custom_prompt)
                # Preserve quality metrics from original frame extraction
                analysis["blur_score"] = frame_data.get("blur_score", 0.0)
                analysis["brightness"] = frame_data.get("brightness", 0.0)
                frame_analyses.append(analysis)

        # 5. Transcribe audio
        transcription_result = transcribe_audio_task(temp_path, job_id)

        # 5b. Generate hierarchical summaries (scenes -> chapters -> video)
        video_summary = None
        key_topics = []
        if config.get("generate_summaries", True):
            try:
                update_job_status(
                    job_id, "processing", 68, "summarizing", "Generating hierarchical summaries..."
                )

                from services.hierarchical_summarizer import HierarchicalSummarizer, SummaryConfig
                from services.scene_analyzer import Scene, VideoStructure

                summarizer = HierarchicalSummarizer()
                summary_config = SummaryConfig(
                    scene_summary_max_tokens=250,
                    chapter_summary_max_tokens=350,
                    video_summary_max_tokens=600,
                )

                # Build scene structure from analyses
                scenes = []
                duration_sec = float(metadata.get("duration", 0) or 0)
                frames_count = len(frame_analyses)

                if frames_count > 0:
                    # Group frames into scenes (approx 5-10 frames per scene)
                    frames_per_scene = max(3, frames_count // 10)

                    for scene_idx in range(0, frames_count, frames_per_scene):
                        scene_frames = frame_analyses[scene_idx : scene_idx + frames_per_scene]
                        if not scene_frames:
                            continue

                        scene_start_time = scene_frames[0].get("timestamp", 0)
                        scene_end_time = scene_frames[-1].get("timestamp", scene_start_time + 10)
                        start_frame_num = scene_frames[0].get("frame_number", scene_idx)
                        end_frame_num = scene_frames[-1].get(
                            "frame_number", scene_idx + len(scene_frames) - 1
                        )

                        # Combine visual descriptions
                        visual_desc = " ".join(
                            [f.get("analysis", "")[:500] for f in scene_frames if f.get("analysis")]
                        )[:2000]

                        # Keyframe indices (use middle frame of scene)
                        keyframe_indices = [scene_idx + len(scene_frames) // 2]

                        scene = Scene(
                            scene_id=scene_idx // frames_per_scene,
                            start_time=scene_start_time,
                            end_time=scene_end_time,
                            start_frame=start_frame_num,
                            end_frame=end_frame_num,
                            duration=scene_end_time - scene_start_time,
                            keyframe_indices=keyframe_indices,
                            visual_description=visual_desc,
                            transcript_segment="",
                            detected_objects=[],
                        )
                        scenes.append(scene)

                if scenes:
                    # Create video structure
                    structure = VideoStructure(
                        media_id=video_id,
                        total_duration=duration_sec,
                        total_frames=len(frames),
                        scenes=scenes,
                        chapters=[],
                    )

                    # Generate summaries (async)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        structure = loop.run_until_complete(
                            summarizer.process_video_hierarchy(structure, summary_config)
                        )
                        video_summary = structure.video_summary
                        key_topics = structure.key_topics or []
                        logger.info(
                            f"Generated hierarchical summaries: {len(scenes)} scenes, summary: {len(video_summary or '')} chars"
                        )
                    finally:
                        loop.close()

            except Exception as e:
                logger.warning(f"Hierarchical summarization skipped: {e}")
                import traceback

                logger.debug(traceback.format_exc())

        # 6. Generate embeddings
        analysis_texts = [a.get("analysis", "") for a in frame_analyses if a.get("analysis")]
        embeddings = (
            generate_embeddings_batch_task(analysis_texts, job_id) if analysis_texts else []
        )

        # 7. Index in Knowledge Graph (Neo4j) + store embeddings
        graph_indexed = False
        if config.get("index_graph", True):
            update_job_status(
                job_id, "processing", 80, "graph", "Indexing in Knowledge Graph (Neo4j)..."
            )
            try:
                from models.graph_models import FrameNode, VideoNode
                from services.knowledge_graph import KnowledgeGraphService

                graph = KnowledgeGraphService()
                graph.initialize_schema()

                # Avoid duplicates if reprocessing the same video
                try:
                    graph.delete_video_graph(video_id)
                except Exception:
                    pass

                title = video_id
                file_size_bytes = 0
                if _db_service:
                    try:
                        existing = _db_service.get_media(video_id)
                        if existing:
                            title = existing.original_filename or title
                            file_size_bytes = int(existing.file_size or 0)
                    except Exception:
                        pass

                # resolution comes as "{w}x{h}"
                w, h = 0, 0
                try:
                    res = str(metadata.get("resolution", "0x0"))
                    w_str, h_str = res.split("x")
                    w, h = int(w_str), int(h_str)
                except Exception:
                    pass

                from pathlib import Path

                fmt = Path(blob_name).suffix.lstrip(".") or "mp4"

                video_node = VideoNode(
                    video_id=video_id,
                    title=title,
                    duration_seconds=float(metadata.get("duration", 0) or 0),
                    fps=float(metadata.get("fps", 0) or 0),
                    resolution=(w, h),
                    file_size_bytes=file_size_bytes,
                    format=fmt,
                    total_frames=int(metadata.get("total_frames", 0) or 0),
                    extracted_frames=len(frames),
                    processing_config=config,
                )
                graph.create_video_node(video_node)

                # Create scenes (FFmpeg scene detection) for navigation/timeline
                scene_nodes = []
                try:
                    from models.graph_models import SceneNode
                    from services.scene_analyzer import SceneAnalyzer

                    analyzer = SceneAnalyzer()
                    duration_sec = float(metadata.get("duration", 0) or 0)
                    fps_val = float(metadata.get("fps", 30) or 30)

                    boundaries = analyzer.detect_scene_changes(temp_path, duration_sec)
                    detected_scenes = analyzer.build_scenes_from_boundaries(
                        boundaries,
                        duration_sec,
                        fps_val,
                        frame_analyses=frame_analyses,  # Pass frame analyses for scene descriptions
                    )

                    for s in detected_scenes:
                        sn = SceneNode(
                            video_id=video_id,
                            start_time=float(s.start_time),
                            end_time=float(s.end_time),
                            scene_index=int(s.scene_id),
                            description=s.visual_description,
                            visual_change_score=float(getattr(s, "visual_change_score", 0.0)),
                            dominant_colors=getattr(s, "dominant_colors", None) or [],
                            transition_type=getattr(s, "transition_type", "cut"),
                        )
                        graph.create_scene_node(sn)
                        scene_nodes.append(sn)

                except Exception as e:
                    logger.warning(f"Scene detection/indexing skipped: {e}")

                # 7c. Group scenes into chapters
                chapter_nodes = []
                if scene_nodes and len(scene_nodes) >= 2:
                    try:
                        from models.graph_models import ChapterNode

                        # Group scenes into chapters (adaptive: 3-5 scenes per chapter)
                        scenes_per_chapter = max(2, min(5, len(scene_nodes) // 3 or 2))
                        chapter_groups = [
                            scene_nodes[i : i + scenes_per_chapter]
                            for i in range(0, len(scene_nodes), scenes_per_chapter)
                        ]

                        client = None
                        try:
                            from core.config import create_azure_openai_client

                            client = create_azure_openai_client()
                        except Exception:
                            pass

                        for idx, group in enumerate(chapter_groups):
                            ch_start = min(s.start_time for s in group)
                            ch_end = max(s.end_time for s in group)
                            scene_descs = [
                                f"[{s.start_time:.1f}s-{s.end_time:.1f}s] {s.description or 'No description'}"
                                for s in group
                            ]

                            # Generate chapter title + summary via LLM
                            title = f"Chapter {idx + 1}"
                            summary = ""
                            topics: list[str] = []

                            if client:
                                try:
                                    import json as _json

                                    from core.config import settings as _ch_settings

                                    ch_prompt = (
                                        "Given these consecutive video scenes, generate a concise chapter title and summary.\n\n"
                                        f"Scenes:\n" + "\n".join(scene_descs) + "\n\n"
                                        'Respond with JSON: {"title": "3-6 word title", "summary": "1-2 sentence summary", "topics": ["topic1", "topic2"]}'
                                    )
                                    ch_response = client.chat.completions.create(
                                        model=_ch_settings.azure.openai_deployment_gpt,
                                        messages=[{"role": "user", "content": ch_prompt}],
                                        max_tokens=200,
                                        temperature=0.3,
                                        response_format={"type": "json_object"},
                                    )
                                    ch_data = _json.loads(
                                        ch_response.choices[0].message.content
                                    )
                                    title = ch_data.get("title", title)
                                    summary = ch_data.get("summary", "")
                                    topics = ch_data.get("topics", [])
                                except Exception as ch_err:
                                    logger.debug(
                                        f"Chapter summary generation failed: {ch_err}"
                                    )

                            chapter = ChapterNode(
                                video_id=video_id,
                                start_time=ch_start,
                                end_time=ch_end,
                                chapter_index=idx,
                                title=title,
                                summary=summary,
                                topics=topics,
                                detection_method="auto",
                            )
                            graph.create_chapter_node(chapter)
                            chapter_nodes.append(chapter)

                        logger.info(
                            f"Created {len(chapter_nodes)} chapters for video {video_id}"
                        )
                    except Exception as e:
                        logger.warning(f"Chapter creation skipped: {e}")
                        processing_warnings.append(f"Chapter creation error: {e}")

                # Create frames + store embeddings in the node
                frame_nodes_with_embeddings: list[tuple[FrameNode, list[float] | None]] = []
                embedding_idx = 0
                for a in frame_analyses:
                    text = a.get("analysis")
                    emb = None
                    if text:
                        if embedding_idx < len(embeddings):
                            emb = embeddings[embedding_idx]
                        embedding_idx += 1

                    frame_node = FrameNode(
                        video_id=video_id,
                        timestamp=float(a.get("timestamp", 0) or 0),
                        frame_number=int(a.get("frame_number") or a.get("index") or 0),
                        description=text,
                        blur_score=float(a.get("blur_score", 0.0)),
                        brightness=float(a.get("brightness", 0.0)),
                    )
                    frame_nodes_with_embeddings.append((frame_node, emb))

                frames_to_create = [f for f, _ in frame_nodes_with_embeddings if f.description]
                if frames_to_create:
                    graph.create_frames_batch(frames_to_create)

                    with graph.get_session() as session:
                        for f, emb in frame_nodes_with_embeddings:
                            if f.description and emb:
                                coarse = emb[:512] if len(emb) >= 512 else emb
                                session.run(
                                    "MATCH (n:Frame {id: $id}) SET n.embedding = $embedding, n.embedding_coarse = $coarse, n.embedding_updated_at = datetime()",
                                    id=f.id,
                                    embedding=emb,
                                    coarse=coarse,
                                )

                # Link frames to scenes by timestamp (if scenes exist)
                if scene_nodes:
                    with graph.get_session() as session:
                        session.run(
                            """
                            MATCH (s:Scene {video_id: $video_id})
                            MATCH (f:Frame {video_id: $video_id})
                            WHERE f.timestamp >= s.start_time AND f.timestamp < s.end_time
                            MERGE (s)-[:CONTAINS]->(f)
                            SET f.scene_id = s.id
                            """,
                            video_id=video_id,
                        )

                graph_indexed = True
            except Exception as e:
                logger.warning(f"Graph indexing skipped: {e}")

        # 8b. Index transcription to Knowledge Graph
        transcript_indexed = 0
        transcript_indexing_error = None
        if transcription_result.get("success") and transcription_result.get("transcription"):
            try:
                update_job_status(
                    job_id,
                    "processing",
                    85,
                    "transcript_graph",
                    "Indexing transcription in Knowledge Graph...",
                )
                transcript_data = transcription_result.get("transcription", {})
                total_segments = len(transcript_data.get("segments", []))

                index_result_transcript = index_transcription_to_graph(
                    video_id, transcript_data, job_id
                )
                transcript_indexed = index_result_transcript.get("indexed", 0)

                # Verify expected segments were indexed
                if total_segments > 0 and transcript_indexed == 0:
                    transcript_indexing_error = index_result_transcript.get(
                        "error", "Unknown indexing error"
                    )
                    logger.error(
                        f"Transcript indexing failed for video {video_id}: "
                        f"expected {total_segments} segments, indexed {transcript_indexed}. "
                        f"Error: {transcript_indexing_error}"
                    )
                elif transcript_indexed < total_segments * 0.9:  # Less than 90%
                    logger.warning(
                        f"Partial transcript indexing for video {video_id}: "
                        f"indexed {transcript_indexed}/{total_segments} segments"
                    )
                else:
                    logger.info(
                        f"Indexed {transcript_indexed}/{total_segments} transcript segments to graph"
                    )

            except Exception as e:
                transcript_indexing_error = str(e)
                logger.error(f"Transcript graph indexing failed: {e}", exc_info=True)

        # 8c. Generate and store embeddings for transcript segments
        if transcript_indexed > 0:
            try:
                update_job_status(
                    job_id,
                    "processing",
                    88,
                    "transcript_embeddings",
                    "Generating transcript embeddings...",
                )

                from services.knowledge_graph import get_knowledge_graph_service

                graph = get_knowledge_graph_service()
                if not graph.is_connected:
                    graph.connect()

                # Collect transcript texts for embedding generation
                transcript_data = transcription_result.get("transcription", {})
                segments = transcript_data.get("segments", [])
                segment_texts = [
                    seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip()
                ]

                if segment_texts:
                    transcript_embeddings = asyncio.run(
                        _video_processor.generate_embeddings_batch(segment_texts, batch_size=16)
                    )

                    emb_stored = 0
                    with graph.get_session() as session:
                        for idx, emb in enumerate(transcript_embeddings):
                            if emb:
                                seg_id = f"{video_id}_audio_{idx}"
                                coarse = emb[:512] if len(emb) >= 512 else emb
                                session.run(
                                    "MATCH (a:AudioSegment {id: $id}) "
                                    "SET a.embedding = $embedding, "
                                    "a.embedding_coarse = $coarse, "
                                    "a.embedding_updated_at = datetime()",
                                    id=seg_id,
                                    embedding=emb,
                                    coarse=coarse,
                                )
                                emb_stored += 1

                    logger.info(f"Stored {emb_stored} transcript embeddings for video {video_id}")
            except Exception as e:
                logger.warning(f"Transcript embedding generation skipped: {e}")

        # 8d. Update Video node with summary and topics in Neo4j
        if video_summary or key_topics:
            try:
                from services.knowledge_graph import get_knowledge_graph_service

                graph = get_knowledge_graph_service()
                if not graph.is_connected:
                    graph.connect()

                with graph.get_session() as session:
                    session.run(
                        """
                        MATCH (v:Video {video_id: $video_id})
                        SET v.summary = $summary,
                            v.topics = $topics,
                            v.summary_updated_at = datetime()
                        """,
                        video_id=video_id,
                        summary=video_summary,
                        topics=key_topics,
                    )
                logger.info(
                    f"Updated Video node with summary ({len(video_summary or '')} chars) and {len(key_topics)} topics"
                )

                # Create Topic graph nodes
                if key_topics:
                    from models.graph_models import TopicNode
                    from uuid import uuid4 as _uuid4

                    topic_nodes = [
                        TopicNode(
                            id=str(_uuid4()),
                            name=topic_name,
                            normalized_name=topic_name.lower().strip().replace(" ", "_"),
                            keywords=[topic_name],
                            relevance_score=1.0 - (i * 0.05),  # decreasing relevance
                        )
                        for i, topic_name in enumerate(key_topics)
                    ]
                    try:
                        graph.create_topic_nodes_batch(topic_nodes, video_id)
                        logger.info(f"Created {len(topic_nodes)} topic nodes for video {video_id}")
                    except Exception as topic_err:
                        logger.debug(f"Topic node creation failed: {topic_err}")
            except Exception as e:
                logger.warning(f"Failed to update Video node with summary: {e}")

        # 9. Clean up temporary files
        cleanup_task(temp_path)

        # Determine if there were warnings during processing
        processing_warnings = []
        if transcript_indexing_error:
            processing_warnings.append(f"Transcript indexing error: {transcript_indexing_error}")
        if not graph_indexed:
            processing_warnings.append("Knowledge graph indexing failed")

        # 9a. Dense temporal chains (link frames, segments, scenes sequentially)
        temporal_chains = {}
        if graph_indexed and config.get("create_temporal_chains", True):
            try:
                update_job_status(
                    job_id, "processing", 91, "temporal_chains", "Creating temporal chains..."
                )
                from services.knowledge_graph import get_knowledge_graph_service

                graph = get_knowledge_graph_service()
                if graph.is_connected:
                    temporal_chains = graph.create_temporal_chains(video_id)
                    logger.info(f"Temporal chains for video {video_id}: {temporal_chains}")
            except Exception as e:
                logger.warning(f"Temporal chain creation skipped: {e}")
                processing_warnings.append(f"Temporal chain error: {e}")

        # 9b. Entity extraction from frame descriptions
        entities_created = 0
        if graph_indexed and config.get("extract_entities", True):
            try:
                update_job_status(
                    job_id,
                    "processing",
                    92,
                    "entity_extraction",
                    "Extracting entities from frames...",
                )
                from services.entity_extractor import get_entity_extractor
                from services.knowledge_graph import get_knowledge_graph_service

                from core.config import settings as _settings

                extractor = get_entity_extractor()
                graph = get_knowledge_graph_service()

                entity_batch: list[tuple] = []
                relation_batch: list[dict] = []
                frame_ids_with_entities: list[str] = []

                for frame_node in frames_to_create:
                    if not frame_node.description:
                        continue
                    try:
                        analysis = extractor.extract_from_description(
                            description=frame_node.description,
                            timestamp=frame_node.timestamp,
                            max_gleanings=_settings.processing.max_gleanings,
                        )
                        entity_nodes = extractor.convert_to_entity_nodes(analysis, video_id)
                        for entity_node in entity_nodes:
                            entity_batch.append((entity_node, frame_node.id))
                        if entity_nodes:
                            frame_ids_with_entities.append(frame_node.id)
                            # Collect semantic relations for this frame
                            frame_relations = extractor.convert_relations_for_graph(
                                analysis, video_id, frame_node.id
                            )
                            relation_batch.extend(frame_relations)
                    except Exception as frame_err:
                        logger.debug(
                            f"Entity extraction failed for frame {frame_node.id}: {frame_err}"
                        )
                        continue

                if entity_batch:
                    entities_created = graph.create_entities_batch(entity_batch)
                    logger.info(f"Created {entities_created} entity nodes for video {video_id}")

                    # Build APPEARS_WITH co-occurrence edges
                    for fid in frame_ids_with_entities:
                        try:
                            graph.create_entity_cooccurrence(fid)
                        except Exception as cooc_err:
                            logger.debug(
                                f"Co-occurrence creation failed for frame {fid}: {cooc_err}"
                            )

                    # Store LLM-extracted semantic relations
                    if relation_batch:
                        try:
                            sem_created = graph.create_semantic_relations_batch(
                                relation_batch
                            )
                            logger.info(
                                f"Created {sem_created} semantic relations for video {video_id}"
                            )
                        except Exception as sem_err:
                            logger.warning(
                                f"Semantic relation creation failed: {sem_err}"
                            )

                    # Link entities to topics
                    try:
                        linked = graph.link_entities_to_topics(video_id)
                        if linked:
                            logger.info(f"Linked {linked} entity-topic pairs for video {video_id}")
                    except Exception as link_err:
                        logger.debug(f"Entity-topic linking failed: {link_err}")

                    # Cross-video entity resolution
                    try:
                        cross_linked = graph.resolve_cross_video_entities(video_id)
                        if cross_linked:
                            logger.info(
                                f"Resolved {cross_linked} cross-video entity matches "
                                f"for video {video_id}"
                            )
                    except Exception as cross_err:
                        logger.debug(f"Cross-video entity resolution failed: {cross_err}")
                else:
                    logger.info(f"No entities extracted for video {video_id}")
            except Exception as e:
                logger.warning(f"Entity extraction skipped: {e}")
                processing_warnings.append(f"Entity extraction error: {e}")

        # 9c. Community detection (post-graph-indexing)
        communities_created = 0
        if graph_indexed and config.get("detect_communities", True):
            try:
                update_job_status(
                    job_id, "processing", 94, "communities", "Detecting entity communities..."
                )
                from services.community_detection_service import (
                    get_community_detection_service,
                )

                community_service = get_community_detection_service()
                community_nodes = community_service.run_pipeline(video_id)
                communities_created = len(community_nodes)
                logger.info(f"Created {communities_created} communities for video {video_id}")
            except Exception as e:
                logger.warning(f"Community detection skipped: {e}")
                processing_warnings.append(f"Community detection error: {e}")

        # 9d. Calculate statistics
        elapsed_time = time.time() - start_time
        total_tokens = sum(a.get("tokens_used", 0) for a in frame_analyses)

        # Determine status: completed_with_warnings if there were partial errors
        final_status = "completed"
        if not graph_indexed or (transcript_indexing_error and transcript_indexed == 0):
            final_status = "completed_with_warnings"

        result = {
            "video_id": video_id,
            "blob_name": blob_name,
            "job_id": job_id,
            "status": final_status,
            "metadata": metadata,
            "frame_analyses": frame_analyses,
            "transcription": transcription_result.get("transcription"),
            "embeddings_count": len(embeddings),
            "transcript_segments_indexed": transcript_indexed,
            "transcript_indexing_error": transcript_indexing_error,
            "video_summary": video_summary,
            "key_topics": key_topics,
            "graph_indexed": graph_indexed,
            "communities_created": communities_created,
            "temporal_chains": temporal_chains or None,
            "total_tokens": total_tokens,
            "processing_time_seconds": round(elapsed_time, 2),
            "processing_warnings": processing_warnings if processing_warnings else None,
        }

        # 10. Update final status
        update_job_status(
            job_id,
            "completed",
            100,
            "done",
            f"Completed in {elapsed_time:.1f}s",
            result_data=result,
        )

        # 11. Update metadata in PostgreSQL
        if _db_service:
            try:
                updates = {
                    "processed": True,
                    "processing_status": final_status,
                    "processing_method": "celery_pipeline",
                    "job_id": job_id,
                    "processing_result": result,
                }

                # Store video metadata with duration
                if metadata.get("duration"):
                    updates["video_metadata"] = {
                        "duration": float(metadata["duration"]),
                        "fps": metadata.get("fps"),
                        "resolution": metadata.get("resolution"),
                    }

                # Store audio data for frontend access
                if transcription_result.get("success") and transcription_result.get(
                    "transcription"
                ):
                    updates["audio_data"] = {
                        "transcription": transcription_result["transcription"],
                        "stats": {
                            "has_audio": True,
                            "total_words": len(
                                transcription_result["transcription"].get("text", "").split()
                            ),
                            "segments_count": len(
                                transcription_result["transcription"].get("segments", [])
                            ),
                        },
                    }

                # Store video summary and topics for chat context
                if video_summary or key_topics:
                    updates["summary_data"] = {
                        "video_summary": video_summary,
                        "key_topics": key_topics,
                    }

                _db_service.update_media(video_id, updates)
            except Exception as e:
                logger.warning(f"Failed to update PostgreSQL: {e}")

        logger.info(f"Pipeline completed for {video_id} in {elapsed_time:.1f}s")
        return result

    except Exception as e:
        logger.error(f"Pipeline failed: {e}\n{traceback.format_exc()}")

        update_job_status(job_id, "failed", 0, "error", f"Error: {str(e)}", str(e))

        # Attempt cleanup
        try:
            if "temp_path" in locals():
                cleanup_task(temp_path)
        except Exception as cleanup_err:
            logger.warning(f"Cleanup failed for job {job_id}: {cleanup_err}")

        raise


# =============================================================================
# Utilities
# =============================================================================


@celery_app.task(name="tasks.video_tasks.get_job_status")
def get_job_status_task(job_id: str) -> dict | None:
    """Get job status from cache."""
    import asyncio

    async def _get():
        cache = await _get_cache_service()
        return await cache.get_job_status(job_id)

    return asyncio.run(_get())


@celery_app.task(name="tasks.video_tasks.cancel_job")
def cancel_job(job_id: str) -> bool:
    """Attempt to cancel a job in progress."""
    from celery.result import AsyncResult

    result = AsyncResult(job_id, app=celery_app)
    if result.state in ["PENDING", "STARTED"]:
        result.revoke(terminate=True)
        update_job_status.delay(job_id, "cancelled", 0, "cancelled", "Job cancelled by user")
        return True
    return False
