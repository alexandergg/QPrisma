"""
Video Processing Tasks para Celery

Tareas asíncronas para procesamiento de video en QPrisma.

Flujo del Pipeline:
    1. process_video_pipeline (orquestador)
       ├── download_video_task
       ├── extract_frames_task
       ├── analyze_frames_task (paralelo)
       ├── generate_embeddings_task (batch)
       ├── transcribe_audio_task
       ├── index_to_neo4j (Knowledge Graph)
       ├── index_transcription_to_graph
       └── cleanup_task

Uso:
    from tasks.video_tasks import process_video_pipeline

    # Iniciar procesamiento
    result = process_video_pipeline.delay(
        video_id="abc123",
        blob_name="videos/mi_video.mp4",
        config={"max_frames": 20}
    )

    # Obtener task_id para tracking
    task_id = result.id

    # Verificar estado
    from tasks.celery_app import celery_app
    status = celery_app.AsyncResult(task_id)
    print(status.state)  # PENDING, STARTED, SUCCESS, FAILURE
    print(status.info)   # Metadata del progreso
"""

import asyncio
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# Asegurar path
backend_path = str(Path(__file__).parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)


# Logging
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Lazy Loading de Servicios (evitar imports pesados al cargar módulo)
# =============================================================================

_services_initialized = False
_blob_service = None
_openai_client = None
_video_processor = None
_cached_processor = None
_cache_service = None
_db_service = None


def _initialize_services():
    """Inicializa servicios de Azure (lazy loading)"""
    global _services_initialized, _blob_service, _openai_client
    global _video_processor, _cache_service, _db_service

    if _services_initialized:
        return

    from dotenv import load_dotenv

    load_dotenv()

    from azure.storage.blob import BlobServiceClient
    from openai import AsyncAzureOpenAI

    # Azure Blob Storage
    conn_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn_string:
        _blob_service = BlobServiceClient.from_connection_string(conn_string)

    # Azure OpenAI (async for non-blocking pipeline)
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if endpoint and api_key:
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        )

    # Video Processor
    if _blob_service and _openai_client:
        from services.video_processor import VideoProcessor

        _video_processor = VideoProcessor(
            openai_client=_openai_client,
            blob_service=_blob_service,
            container_name=os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media"),
        )

    # PostgreSQL Database Service (replaces Cosmos DB)
    from services.database_service import get_database_service

    _db_service = get_database_service()

    _services_initialized = True
    logger.info("Services initialized for Celery worker")


async def _get_cache_service():
    """Obtiene el servicio de cache (async)"""
    global _cache_service
    if _cache_service is None:
        from services.cache_service import CacheService

        _cache_service = CacheService()
        await _cache_service.connect()
    return _cache_service


# =============================================================================
# Tasks de Bajo Nivel
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
    Actualiza el estado de un job en cache y notifica via Redis Pub/Sub.
    Esta task se usa para notificar progreso a los clientes en tiempo real.

    Usa Redis síncrono para evitar problemas con event loops en Celery.
    """
    import json

    import redis

    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url)

        # 1. Guardar estado del job en Redis (cache)
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

        # Guardar en Redis con TTL de 1 hora
        cache_key = f"job_status:{job_id}"
        redis_client.setex(cache_key, 3600, json.dumps(status_data))

        logger.info(f"Job {job_id}: {status} ({progress}%) - {stage}")

        # 2. Publicar evento a Redis Pub/Sub para WebSockets
        if status == "completed":
            event_type = "completed"
            event_data = {"result": result_data}
        elif status == "failed":
            event_type = "failed"
            event_data = {"error": error}
        else:
            event_type = "progress"
            event_data = {"progress": progress, "stage": stage, "message": message}

        pubsub_message = json.dumps({
            "type": event_type,
            "job_id": job_id,
            "data": event_data
        })

        redis_client.publish("qprisma:websocket:events", pubsub_message)
        logger.debug(f"Published WebSocket event for job {job_id}: {event_type}")

        redis_client.close()

    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        # No fallar la task, solo logear

    return {"job_id": job_id, "status": status}


@celery_app.task(
    bind=True, name="tasks.video_tasks.download_video_task", max_retries=3, default_retry_delay=30
)
def download_video_task(self, blob_name: str, job_id: str) -> dict:
    """
    Descarga un video de Azure Blob Storage a un archivo temporal.

    Returns:
        Dict con temp_path del archivo descargado
    """
    _initialize_services()

    try:
        update_job_status.delay(job_id, "processing", 5, "downloading", "Descargando video...")

        # Crear archivo temporal
        suffix = Path(blob_name).suffix or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_path = tmp_file.name

        # Descargar
        blob_client = _blob_service.get_blob_client(
            container=os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media"), blob=blob_name
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
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="tasks.video_tasks.extract_frames_task", max_retries=2)
def extract_frames_task(self, download_result: dict, job_id: str, max_frames: int = 20) -> dict:
    """
    Extrae frames de un video usando FFmpeg.

    Returns:
        Dict con lista de frames (bytes) y metadata
    """
    _initialize_services()
    import cv2

    try:
        update_job_status.delay(
            job_id, "processing", 15, "extracting", f"Extrayendo {max_frames} frames..."
        )

        temp_path = download_result["temp_path"]

        # Obtener metadata del video
        cap = cv2.VideoCapture(temp_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0

        # Helper functions for frame quality metrics
        def calculate_blur_score(frame) -> float:
            """Calculate blur using Laplacian variance. Higher = sharper."""
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            # Normalize to 0-1 range (typical values 0-500+, cap at 500)
            return min(laplacian_var / 500.0, 1.0)

        def calculate_brightness(frame) -> float:
            """Calculate average brightness. 0=dark, 1=bright."""
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return float(gray.mean() / 255.0)

        # Extraer frames distribuidos uniformemente
        frames_data = []
        if total_frames > 0:
            step = max(1, total_frames // max_frames)
            frame_positions = [i * step for i in range(min(max_frames, total_frames))]

            for idx, pos in enumerate(frame_positions):
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()

                if ret:
                    # Calculate quality metrics
                    blur_score = calculate_blur_score(frame)
                    brightness = calculate_brightness(frame)

                    # Codificar como JPEG
                    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    frame_bytes = buffer.tobytes()

                    timestamp = pos / fps if fps > 0 else 0
                    frames_data.append(
                        {
                            "index": idx,
                            "frame_number": pos,
                            "timestamp": round(timestamp, 2),
                            "image_bytes": frame_bytes,  # Nota: bytes se serializan en base64
                            "blur_score": round(blur_score, 4),
                            "brightness": round(brightness, 4),
                        }
                    )

        cap.release()

        logger.info(f"Extracted {len(frames_data)} frames from {temp_path}")

        return {
            "frames": frames_data,
            "metadata": {
                "fps": fps,
                "total_frames": total_frames,
                "duration": round(duration, 2),
                "resolution": f"{width}x{height}",
                "frames_extracted": len(frames_data),
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
    rate_limit="30/m",  # Max 30 por minuto (proteger Azure OpenAI)
)
def analyze_frame_task(
    self, frame_data: dict, job_id: str, custom_prompt: str | None = None
) -> dict:
    """
    Analiza un frame individual con GPT-4V.
    Rate limited para proteger cuota de Azure OpenAI.
    """
    _initialize_services()
    import base64

    import cv2
    import numpy as np

    try:
        # Decodificar frame
        frame_bytes = (
            base64.b64decode(frame_data["image_bytes"])
            if isinstance(frame_data["image_bytes"], str)
            else frame_data["image_bytes"]
        )

        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Analizar con GPT-4V
        analysis = asyncio.run(_video_processor.analyze_frame_with_gpt4v(
            frame,
            custom_prompt=custom_prompt,
            timestamp=frame_data.get("timestamp"),
        ))

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
            raise self.retry(exc=e)
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
    """Genera embedding para un texto"""
    _initialize_services()

    if not text or not text.strip():
        return []

    try:
        return asyncio.run(_video_processor.generate_embedding(text))
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return []


@celery_app.task(bind=True, name="tasks.video_tasks.generate_embeddings_batch_task", max_retries=2)
def generate_embeddings_batch_task(self, texts: list[str], job_id: str) -> list[list[float]]:
    """Genera embeddings en batch"""
    _initialize_services()

    try:
        update_job_status.delay(
            job_id, "processing", 75, "embeddings", f"Generando {len(texts)} embeddings..."
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
    """Transcribe el audio del video con Whisper"""
    _initialize_services()

    try:
        update_job_status.delay(job_id, "processing", 60, "transcribing", "Transcribiendo audio...")

        if _video_processor and _video_processor.audio_processor:
            # process_video_audio is async — must run in event loop
            result = asyncio.run(_video_processor.audio_processor.process_video_audio(temp_path))
            transcription = result.get("transcription", {})
            return {"transcription": transcription, "success": True}
        else:
            logger.warning("Audio processor not available")
            return {
                "transcription": None,
                "success": False,
                "error": "Audio processor not available",
            }

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return {"transcription": None, "success": False, "error": str(e)}


@celery_app.task(bind=True, name="tasks.video_tasks.cleanup_task")
def cleanup_task(self, temp_path: str):
    """Limpia archivos temporales"""
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
    Indexa los segmentos de transcripción a Neo4j Knowledge Graph.

    Args:
        video_id: ID del video
        transcription_data: Datos de transcripción con segmentos
        job_id: ID del job para actualizar estado

    Returns:
        Dict con estadísticas de indexación
    """
    _initialize_services()

    try:
        from models.graph_models import AudioSegmentNode
        from services.knowledge_graph import get_knowledge_graph_service

        graph = get_knowledge_graph_service()
        
        # Asegurar conexión a Neo4j
        if not graph.is_connected:
            graph.connect()

        # Obtener segmentos de la transcripción
        segments = transcription_data.get("segments", [])
        if not segments:
            logger.info(f"No transcript segments to index for video {video_id}")
            return {"indexed": 0, "success": True, "message": "No segments to index"}
        
        logger.info(f"Starting transcript indexing: {len(segments)} segments for video {video_id}")

        # Eliminar transcripciones existentes para este video
        try:
            deleted = graph.delete_video_transcripts(video_id)
            if deleted > 0:
                logger.info(f"Deleted {deleted} existing transcript segments for video {video_id}")
        except Exception as e:
            logger.warning(f"Could not delete existing transcripts: {e}")

        # Crear nodos AudioSegment
        language = transcription_data.get("language", "unknown")
        audio_segments = []

        for idx, segment in enumerate(segments):
            segment_node = AudioSegmentNode(
                id=f"{video_id}_audio_{idx}",  # Usar índice para evitar IDs duplicados
                video_id=video_id,
                start_time=segment.get("start", 0),
                end_time=segment.get("end", 0),
                text=segment.get("text", "").strip(),
                language=language,
                confidence=segment.get("avg_logprob", 0) if segment.get("avg_logprob") else 0.9,
            )
            audio_segments.append(segment_node)

        # Indexar en batch (con manejo de batches internos)
        created = graph.create_audio_segments_batch(audio_segments)
        
        success = created > 0 or len(segments) == 0
        
        if created < len(segments) * 0.5:  # Menos del 50% indexado
            logger.error(
                f"Transcript indexing partial failure: only {created}/{len(segments)} segments indexed"
            )

        logger.info(f"Indexed {created}/{len(segments)} transcript segments for video {video_id}")

        return {
            "indexed": created,
            "total_segments": len(segments),
            "language": language,
            "success": success,
            "error": None if success else f"Only indexed {created}/{len(segments)} segments"
        }

    except Exception as e:
        error_msg = f"Failed to index transcription for video {video_id}: {e}"
        logger.error(error_msg, exc_info=True)
        
        # Reintentar si es un error de conexión
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            try:
                self.retry(countdown=5, exc=e)
            except Exception:
                pass  # Max retries alcanzados
        
        return {"indexed": 0, "success": False, "error": str(e)}


# =============================================================================
# Pipeline Principal
# =============================================================================


@celery_app.task(bind=True, name="tasks.video_tasks.process_video_pipeline", max_retries=1)
def process_video_pipeline(self, video_id: str, blob_name: str, config: dict | None = None) -> dict:
    """
    Pipeline completo de procesamiento de video.

    Este es el orquestador principal que coordina todas las sub-tareas.

    Args:
        video_id: ID único del video
        blob_name: Nombre del blob en Azure Storage
        config: Configuración opcional (max_frames, custom_prompt, etc.)

    Returns:
        Dict con resultados completos del procesamiento
    """
    _initialize_services()

    job_id = self.request.id or f"job_{video_id}"
    config = config or {}
    max_frames = config.get("max_frames", 20)
    custom_prompt = config.get("custom_prompt")

    start_time = time.time()

    try:
        # 1. Iniciar job
        update_job_status(
            job_id, "processing", 0, "started", f"Iniciando procesamiento de {blob_name}"
        )

        # 2. Descargar video
        download_result = download_video_task(blob_name, job_id)
        temp_path = download_result["temp_path"]

        # 3. Extraer frames
        extraction_result = extract_frames_task(download_result, job_id, max_frames)
        frames = extraction_result["frames"]
        metadata = extraction_result["metadata"]

        # 4. Analizar frames con Batch API (50% más barato)
        update_job_status(
            job_id, "processing", 25, "analyzing", f"Analizando {len(frames)} frames con Batch API..."
        )

        frame_analyses = []
        try:
            # Usar Batch API para análisis de frames (50% ahorro)
            import base64

            from services.batch_processor import BatchProcessor

            batch_proc = BatchProcessor(_video_processor.openai_client)

            # Preparar frames para Batch API
            frames_for_batch = []
            for frame_data in frames:
                image_bytes = frame_data.get("image_bytes", b"")
                if isinstance(image_bytes, bytes):
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                else:
                    image_base64 = image_bytes

                frames_for_batch.append({
                    "frame_number": frame_data.get("frame_number", frame_data.get("index", 0)),
                    "timestamp": frame_data.get("timestamp", 0),
                    "image_base64": image_base64,
                })

            # Enviar batch job
            update_job_status(
                job_id, "processing", 30, "batch_submit", f"Enviando {len(frames)} frames a Batch API..."
            )
            vision_requests = batch_proc.create_vision_batch_requests(frames_for_batch, custom_prompt)
            vision_batch_id = asyncio.run(batch_proc.submit_batch_job(
                vision_requests, description=f"Celery: {blob_name} ({len(frames)} frames)"
            ))
            logger.info(f"Batch job created: {vision_batch_id}")

            # Esperar completación
            update_job_status(
                job_id, "processing", 35, "batch_wait", "Esperando Batch API (típicamente 3-5 min)..."
            )
            success = asyncio.run(batch_proc.wait_for_batch_completion(
                vision_batch_id, check_interval=30, max_wait_time=1800
            ))

            if not success:
                raise Exception(f"Batch job timeout or failed: {vision_batch_id}")

            # Obtener resultados
            update_job_status(
                job_id, "processing", 55, "batch_results", "Procesando resultados de Batch API..."
            )
            vision_results = asyncio.run(batch_proc.get_batch_results(vision_batch_id))
            parsed_analyses = batch_proc.parse_vision_results(vision_results)

            # Convertir a formato esperado
            for i, frame_data in enumerate(frames):
                frame_id = f"frame_{frame_data.get('frame_number', i)}"
                analysis_text = parsed_analyses.get(frame_id, {}).get("analysis", "")
                frame_analyses.append({
                    "index": i,
                    "frame_number": frame_data.get("frame_number", i),
                    "timestamp": frame_data.get("timestamp", 0),
                    "analysis": analysis_text,
                    "tokens_used": 0,
                    "blur_score": frame_data.get("blur_score", 0.0),
                    "brightness": frame_data.get("brightness", 0.0),
                })

            logger.info(f"Batch API completed: {len(frame_analyses)} frames analyzed")

        except Exception as batch_error:
            logger.warning(f"Batch API failed, falling back to individual calls: {batch_error}")
            # Fallback: análisis secuencial (más caro pero funciona)
            import base64
            for i, frame_data in enumerate(frames):
                progress = 25 + int((i / len(frames)) * 35)
                update_job_status(
                    job_id, "processing", progress, "analyzing", f"Analizando frame {i+1}/{len(frames)} (fallback)"
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

        # 5. Transcribir audio
        transcription_result = transcribe_audio_task(temp_path, job_id)

        # 5b. Generar resúmenes jerárquicos (escenas -> capítulos -> video)
        video_summary = None
        key_topics = []
        if config.get("generate_summaries", True):
            try:
                update_job_status(
                    job_id, "processing", 68, "summarizing", "Generando resúmenes jerárquicos..."
                )

                from services.hierarchical_summarizer import HierarchicalSummarizer, SummaryConfig
                from services.scene_analyzer import Scene, VideoStructure

                summarizer = HierarchicalSummarizer()
                summary_config = SummaryConfig(
                    scene_summary_max_tokens=250,
                    chapter_summary_max_tokens=350,
                    video_summary_max_tokens=600,
                )

                # Construir estructura de escenas desde los análisis
                scenes = []
                duration_sec = float(metadata.get("duration", 0) or 0)
                frames_count = len(frame_analyses)

                if frames_count > 0:
                    # Agrupar frames en escenas (aprox 5-10 frames por escena)
                    frames_per_scene = max(3, frames_count // 10)

                    for scene_idx in range(0, frames_count, frames_per_scene):
                        scene_frames = frame_analyses[scene_idx:scene_idx + frames_per_scene]
                        if not scene_frames:
                            continue

                        start_time = scene_frames[0].get("timestamp", 0)
                        end_time = scene_frames[-1].get("timestamp", start_time + 10)
                        start_frame_num = scene_frames[0].get("frame_number", scene_idx)
                        end_frame_num = scene_frames[-1].get("frame_number", scene_idx + len(scene_frames) - 1)

                        # Combinar descripciones visuales
                        visual_desc = " ".join([
                            f.get("analysis", "")[:500] for f in scene_frames if f.get("analysis")
                        ])[:2000]

                        # Keyframe indices (use middle frame of scene)
                        keyframe_indices = [scene_idx + len(scene_frames) // 2]

                        scene = Scene(
                            scene_id=scene_idx // frames_per_scene,
                            start_time=start_time,
                            end_time=end_time,
                            start_frame=start_frame_num,
                            end_frame=end_frame_num,
                            duration=end_time - start_time,
                            keyframe_indices=keyframe_indices,
                            visual_description=visual_desc,
                            transcript_segment="",
                            detected_objects=[],
                        )
                        scenes.append(scene)

                if scenes:
                    # Crear estructura de video
                    structure = VideoStructure(
                        media_id=video_id,
                        total_duration=duration_sec,
                        total_frames=len(frames),
                        scenes=scenes,
                        chapters=[],
                    )

                    # Generar resúmenes (async)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        structure = loop.run_until_complete(
                            summarizer.process_video_hierarchy(structure, summary_config)
                        )
                        video_summary = structure.video_summary
                        key_topics = structure.key_topics or []
                        logger.info(f"Generated hierarchical summaries: {len(scenes)} scenes, summary: {len(video_summary or '')} chars")
                    finally:
                        loop.close()

            except Exception as e:
                logger.warning(f"Hierarchical summarization skipped: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        # 6. Generar embeddings
        analysis_texts = [a.get("analysis", "") for a in frame_analyses if a.get("analysis")]
        embeddings = (
            generate_embeddings_batch_task(analysis_texts, job_id) if analysis_texts else []
        )

        # 7. Indexar en Knowledge Graph (Neo4j) + almacenar embeddings
        graph_indexed = False
        if config.get("index_graph", True):
            update_job_status(
                job_id, "processing", 80, "graph", "Indexando en Knowledge Graph (Neo4j)..."
            )
            try:
                from models.graph_models import FrameNode, VideoNode
                from services.knowledge_graph import KnowledgeGraphService

                graph = KnowledgeGraphService()
                graph.initialize_schema()

                # Evitar duplicados si re-procesamos el mismo video
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

                # resolution viene como "{w}x{h}"
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

                # Crear escenas (FFmpeg scene detection) para navegación/timeline
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
                            visual_change_score=float(getattr(s, 'visual_change_score', 0.0)),
                            dominant_colors=getattr(s, 'dominant_colors', None) or [],
                            transition_type=getattr(s, 'transition_type', 'cut'),
                        )
                        graph.create_scene_node(sn)
                        scene_nodes.append(sn)

                except Exception as e:
                    logger.warning(f"Scene detection/indexing skipped: {e}")

                # Crear frames + guardar embeddings en el nodo
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
                                session.run(
                                    "MATCH (n:Frame {id: $id}) SET n.embedding = $embedding, n.embedding_updated_at = datetime()",
                                    id=f.id,
                                    embedding=emb,
                                )

                # Vincular frames a escenas por timestamp (si existen escenas)
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
                    "Indexando transcripción en Knowledge Graph...",
                )
                transcript_data = transcription_result.get("transcription", {})
                total_segments = len(transcript_data.get("segments", []))
                
                index_result_transcript = index_transcription_to_graph(
                    video_id, transcript_data, job_id
                )
                transcript_indexed = index_result_transcript.get("indexed", 0)
                
                # Verificar que se indexaron los segmentos esperados
                if total_segments > 0 and transcript_indexed == 0:
                    transcript_indexing_error = index_result_transcript.get("error", "Unknown indexing error")
                    logger.error(
                        f"Transcript indexing failed for video {video_id}: "
                        f"expected {total_segments} segments, indexed {transcript_indexed}. "
                        f"Error: {transcript_indexing_error}"
                    )
                elif transcript_indexed < total_segments * 0.9:  # Menos del 90%
                    logger.warning(
                        f"Partial transcript indexing for video {video_id}: "
                        f"indexed {transcript_indexed}/{total_segments} segments"
                    )
                else:
                    logger.info(f"Indexed {transcript_indexed}/{total_segments} transcript segments to graph")
                    
            except Exception as e:
                transcript_indexing_error = str(e)
                logger.error(f"Transcript graph indexing failed: {e}", exc_info=True)

        # 8c. Update Video node with summary and topics in Neo4j
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
                logger.info(f"Updated Video node with summary ({len(video_summary or '')} chars) and {len(key_topics)} topics")
            except Exception as e:
                logger.warning(f"Failed to update Video node with summary: {e}")

        # 9. Limpiar archivos temporales
        cleanup_task(temp_path)

        # 9. Calcular estadísticas
        elapsed_time = time.time() - start_time
        total_tokens = sum(a.get("tokens_used", 0) for a in frame_analyses)
        
        # Determinar si hubo warnings durante el procesamiento
        processing_warnings = []
        if transcript_indexing_error:
            processing_warnings.append(f"Transcript indexing error: {transcript_indexing_error}")
        
        # Determinar estado: completed_with_warnings si hubo errores parciales
        final_status = "completed"
        if transcript_indexing_error and transcript_indexed == 0:
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
            "total_tokens": total_tokens,
            "processing_time_seconds": round(elapsed_time, 2),
            "processing_warnings": processing_warnings if processing_warnings else None,
        }

        # 10. Actualizar estado final
        update_job_status(
            job_id,
            "completed",
            100,
            "done",
            f"Completado en {elapsed_time:.1f}s",
            result_data=result,
        )

        # 11. Actualizar metadata en PostgreSQL
        if _db_service:
            try:
                updates = {
                    "processed": True,
                    "processing_status": "completed",
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
                if transcription_result.get("success") and transcription_result.get("transcription"):
                    updates["audio_data"] = {
                        "transcription": transcription_result["transcription"],
                        "stats": {
                            "has_audio": True,
                            "total_words": len(transcription_result["transcription"].get("text", "").split()),
                            "segments_count": len(transcription_result["transcription"].get("segments", [])),
                        }
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

        # Intentar limpiar
        try:
            if "temp_path" in locals():
                cleanup_task(temp_path)
        except:
            pass

        raise


# =============================================================================
# Utilidades
# =============================================================================


@celery_app.task(name="tasks.video_tasks.get_job_status")
def get_job_status_task(job_id: str) -> dict | None:
    """Obtiene el estado de un job desde cache"""
    import asyncio

    async def _get():
        cache = await _get_cache_service()
        return await cache.get_job_status(job_id)

    return asyncio.run(_get())


@celery_app.task(name="tasks.video_tasks.cancel_job")
def cancel_job(job_id: str) -> bool:
    """Intenta cancelar un job en progreso"""
    from celery.result import AsyncResult

    result = AsyncResult(job_id, app=celery_app)
    if result.state in ["PENDING", "STARTED"]:
        result.revoke(terminate=True)
        update_job_status.delay(job_id, "cancelled", 0, "cancelled", "Job cancelado por usuario")
        return True
    return False
