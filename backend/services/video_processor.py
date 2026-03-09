"""
Video Processing Service
Extracts frames from videos, analyzes them with GPT-4o Vision, and generates embeddings.
Uses ultra-fast FFmpeg and Azure OpenAI Batch API (50% cheaper).
"""

import asyncio
import base64
import io
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator
from typing import Any

import cv2
import numpy as np
from azure.storage.blob import BlobServiceClient
from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError
from PIL import Image

from core.config import settings
from models.ffmpeg_config import (
    FFmpegProcessingConfig,
    ProcessingPipeline,
    ProcessingPreset,
    get_preset_config,
)
from services.audio_processor import AudioProcessor
from services.batch_processor import BatchProcessor
from services.ffmpeg_processor import FFmpegVideoProcessor
from services.processing_metrics import PipelineMetrics

logger = logging.getLogger(__name__)


class VideoProcessor:
    """
    Processes videos: frame extraction, analysis with GPT-4V, embeddings, audio.

    Attributes:
        openai_client: Azure OpenAI client for vision analysis and embeddings.
        blob_service: Azure Blob Storage client for media storage.
        container_name: Name of the blob container for media.
    """

    # Processing constants
    BATCH_CHECK_INTERVAL_SECONDS = 10  # Start at 10s, exponential backoff
    BATCH_MAX_WAIT_TIME_SECONDS = 600  # 10 minutes
    DEFAULT_PARALLEL_WORKERS = 4

    # Adaptive token budget thresholds (image entropy)
    COMPLEXITY_LOW_THRESHOLD = 5.5
    COMPLEXITY_HIGH_THRESHOLD = 7.0
    TOKEN_BUDGET = {"low": 300, "medium": 600, "high": 900}

    def __init__(
        self,
        openai_client: AzureOpenAI | AsyncAzureOpenAI,
        blob_service: BlobServiceClient,
        container_name: str = "media",
    ):
        self.openai_client = openai_client
        self.blob_service = blob_service
        self.container_name = container_name
        self.gpt_deployment = settings.azure.openai_deployment_gpt
        self.embedding_deployment = settings.azure.openai_deployment_embedding
        # Rate limit for Whisper API (requests per minute)
        self.audio_processor = AudioProcessor(
            openai_client, rate_limit_rpm=settings.azure.openai_whisper_rpm
        )

    def delete_video(self, blob_name: str) -> None:
        """Delete a video blob from Azure Storage."""
        blob_client = self.blob_service.get_blob_client(
            container=self.container_name, blob=blob_name
        )
        blob_client.delete_blob()

    async def _download_blob_streaming(self, blob_name: str, file_path: str) -> None:
        """
        Stream download a blob from Azure Storage to a local file.

        Uses chunked download with max_concurrency for parallel transfer.

        Args:
            blob_name: Name of the blob in Azure Storage
            file_path: Local path to write the file
        """
        blob_client = self.blob_service.get_blob_client(
            container=self.container_name, blob=blob_name
        )
        with open(file_path, "wb") as f:
            blob_client.download_blob(max_concurrency=8).readinto(f)

    def frame_to_base64(self, frame: np.ndarray, quality: int = 85) -> str:
        """Convert a numpy frame to base64 JPEG."""
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    def _encode_frame_optimized(
        self,
        frame_data: bytes | np.ndarray,
        max_dimension: int | None = None,
        use_webp: bool | None = None,
        quality: int | None = None,
    ) -> tuple[str, str]:
        """Encode frame with optimal settings for Vision API.

        Uses WebP by default for 25-35% smaller payloads, with automatic
        resize when frames exceed ``max_dimension``.  Falls back to JPEG
        when ``use_webp`` is ``False`` or the format is set to ``"jpeg"``
        in processing settings.

        Args:
            frame_data: Raw image bytes or numpy array.
            max_dimension: Cap on the largest side (px). ``None`` reads
                from ``settings.processing.frame_max_dimension``.
            use_webp: Explicit override.  ``None`` reads from
                ``settings.processing.frame_encoding_format``.
            quality: Encoding quality 1-100.  ``None`` reads from
                ``settings.processing.frame_encoding_quality``.

        Returns:
            Tuple of ``(base64_data, media_type)`` where *media_type* is
            ``"image/webp"`` or ``"image/jpeg"``.
        """
        proc = settings.processing
        if max_dimension is None:
            max_dimension = proc.frame_max_dimension
        if use_webp is None:
            use_webp = proc.frame_encoding_format.lower() == "webp"
        if quality is None:
            quality = proc.frame_encoding_quality

        if isinstance(frame_data, np.ndarray):
            img = Image.fromarray(frame_data)
        else:
            img = Image.open(io.BytesIO(frame_data))

        # Resize if needed
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buffer = io.BytesIO()
        if use_webp:
            img.save(buffer, format="WebP", quality=quality)
            media_type = "image/webp"
        else:
            img.save(buffer, format="JPEG", quality=quality)
            media_type = "image/jpeg"

        return base64.b64encode(buffer.getvalue()).decode(), media_type

    async def analyze_frame_with_gpt4v(
        self,
        frame: np.ndarray | bytes,
        custom_prompt: str | None = None,
        detail_level: str = "auto",
        *,
        timestamp: float | int | None = None,
        max_tokens: int = 900,
    ) -> dict:
        """
        Analyze a frame with GPT-4o Vision.

        Args:
            frame: Frame as a numpy array or raw image bytes (JPEG/WebP)
            custom_prompt: Custom prompt (optional)
            detail_level: "low", "high" or "auto"

        Returns:
            Dictionary with the frame analysis
        """
        # Convert frame to optimized base64
        base64_image, media_type = self._encode_frame_optimized(frame)

        # Default prompt - optimized for semantic search and RAG
        default_prompt = """You are analyzing a video frame at timestamp {timestamp}s. Provide a comprehensive analysis optimized for semantic search and RAG retrieval.

## SCENE DESCRIPTION
Describe the overall scene: setting (indoor/outdoor), environment type, lighting conditions, visual style, and atmosphere.

## PEOPLE & CHARACTERS
For each person visible:
- Physical appearance (age range, gender, clothing, distinguishing features)
- Position and posture in frame
- Facial expression and apparent emotion
- Role if apparent (presenter, interviewer, audience, etc.)
- Name if displayed (from name tags, lower-thirds, or introduced)

**People count: [exact number of people visible]**

## ON-SCREEN TEXT (OCR) - CRITICAL
Transcribe ALL visible text exactly as shown:
- Slide titles, bullet points, and body text
- Lower-thirds, name captions, titles
- UI elements, buttons, menus (for screen recordings)
- Signs, labels, logos with text
Use quotation marks for exact text.

## OBJECT INVENTORY (CRITICAL FOR COUNTING & REASONING)
List ALL distinct objects visible with counts and positions:
- Format: "[count]x [object] - [position in frame: left/center/right, top/middle/bottom]"
- Example: "2x wooden chairs - center-left", "1x laptop - right, on desk"
- Include colors, materials, sizes, and states (open/closed, on/off)
- Note spatial relationships: "laptop is ON the desk", "cat is BETWEEN the chairs", "person is LEFT OF the screen"

**Total distinct objects: [number]**

## SPATIAL LAYOUT
Describe the spatial arrangement of key elements:
- Foreground vs background elements
- Left-to-right arrangement of people/objects
- Relative positions: above, below, left of, right of, in front of, behind
- Camera angle: close-up, medium shot, wide shot, overhead, etc.

## ACTIONS & NARRATIVE
- What is happening in this exact moment
- Specific action verbs (presenting, demonstrating, explaining, comparing)
- Interactions between people/objects
- Is this a transition, introduction, key point, or conclusion?

## TOPICS & KEYWORDS
List 5-8 keywords/phrases someone might use to find this moment, including proper nouns, technical terms, and topic keywords.

Be thorough but factual. Prioritize information that would help users find this specific moment."""

        resolved_timestamp = timestamp if timestamp is not None else 0
        prompt = custom_prompt or default_prompt.replace("{timestamp}", str(resolved_timestamp))

        try:
            # Azure OpenAI SDK: model parameter must be the deployment name
            completion_params = {
                "model": self.gpt_deployment,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{base64_image}",
                                    "detail": detail_level,
                                },
                            },
                        ],
                    }
                ],
            }

            completion_params["max_completion_tokens"] = max_tokens

            completion_params["temperature"] = 1

            response = await self.openai_client.chat.completions.create(**completion_params)

            analysis = response.choices[0].message.content

            return {
                "analysis": analysis,
                "model": self.gpt_deployment,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
            }

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error in analyze_frame_with_gpt4v: {e}")
            return {"analysis": None, "error": str(e), "model": self.gpt_deployment}
        except Exception as e:
            logger.exception(f"Unexpected error in analyze_frame_with_gpt4v: {e}")
            return {"analysis": None, "error": str(e), "model": self.gpt_deployment}

    async def generate_embedding(self, text: str) -> list[float]:
        """
        Generate an embedding for a text using Azure OpenAI.

        Args:
            text: Text to convert into an embedding.

        Returns:
            List of floats representing the embedding, or empty list on error.
        """
        try:
            response = await self.openai_client.embeddings.create(
                model=self.embedding_deployment, input=text
            )
            return response.data[0].embedding
        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error generating embedding: {e}")
            return []
        except Exception as e:
            logger.exception(f"Unexpected error generating embedding: {e}")
            return []

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Azure OpenAI supports up to 2048 texts per request.  The batch size
        defaults to ``settings.processing.embedding_batch_size`` (512).  On
        API errors the batch is automatically retried at half size.

        Args:
            texts: List of texts to convert into embeddings.
            batch_size: Override batch size (``None`` → use settings).

        Returns:
            List of embeddings, one per input text.
        """
        if not texts:
            logger.warning("generate_embeddings_batch: empty text list")
            return []

        if batch_size is None:
            batch_size = settings.processing.embedding_batch_size

        logger.info(f"Generating embeddings for {len(texts)} texts in batches of {batch_size}")
        embeddings: list[list[float]] = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_num = i // batch_size + 1
            effective_size = len(batch)

            try:
                logger.debug(
                    f"Processing batch {batch_num}/{total_batches} ({effective_size} texts)"
                )

                response = await self.openai_client.embeddings.create(
                    model=self.embedding_deployment, input=batch
                )

                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)

                logger.debug(
                    f"Batch {batch_num}/{total_batches}: {len(batch_embeddings)} embeddings generated"
                )

            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.warning(
                    f"API error in batch {batch_num}/{total_batches} "
                    f"(size={effective_size}): {e} — retrying with half batch size"
                )
                # Adaptive retry: split the failed batch in half and retry
                half = max(1, effective_size // 2)
                logger.info(f"Retrying batch {batch_num} with batch_size={half}")
                for sub_start in range(0, effective_size, half):
                    sub_batch = batch[sub_start : sub_start + half]
                    try:
                        response = await self.openai_client.embeddings.create(
                            model=self.embedding_deployment, input=sub_batch
                        )
                        sub_embeddings = [item.embedding for item in response.data]
                        embeddings.extend(sub_embeddings)
                        logger.debug(f"Retry sub-batch succeeded: {len(sub_embeddings)} embeddings")
                    except (APIError, APIConnectionError, RateLimitError) as retry_err:
                        logger.error(
                            f"Retry sub-batch also failed (size={len(sub_batch)}): {retry_err}"
                        )
                        embeddings.extend([[] for _ in sub_batch])
                    except Exception as retry_err:
                        logger.exception(f"Unexpected error in retry sub-batch: {retry_err}")
                        embeddings.extend([[] for _ in sub_batch])
            except Exception as e:
                logger.exception(f"Unexpected error in batch {batch_num}/{total_batches}: {e}")
                embeddings.extend([[] for _ in batch])

        logger.info(f"Total: {len(embeddings)} embeddings generated")
        return embeddings

    # =========================================================================
    # PROCESSING WITH FFMPEG + BATCH API
    # =========================================================================

    async def _safe_process_audio(
        self,
        video_path: str,
        language: str | None,
        metrics: "PipelineMetrics",
    ) -> dict[str, Any] | None:
        """Process audio, returning ``None`` on failure (non-fatal).

        Wrapped for safe use inside ``asyncio.TaskGroup`` — exceptions
        are caught so audio failure does not cancel the vision batch
        pipeline.
        """
        metrics.start_stage("transcription")
        try:
            logger.info("Processing audio while batch API analyzes frames...")
            audio_data = await self.audio_processor.process_video_audio(
                video_path=video_path,
                language=language,
                video_descriptions=None,
            )
            word_count = (audio_data or {}).get("stats", {}).get("total_words", 0)
            metrics.end_stage("transcription", items_processed=word_count)
            return audio_data
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"Error processing audio (continuing without audio): {e}")
            metrics.end_stage("transcription", items_failed=1, error=str(e))
            return None
        except Exception as e:
            logger.warning(f"Unexpected error processing audio: {e}")
            metrics.end_stage("transcription", items_failed=1, error=str(e))
            return None

    async def process_video_ffmpeg(
        self,
        blob_name: str,
        config: FFmpegProcessingConfig | None = None,
        preset: ProcessingPreset | None = None,
        custom_prompt: str | None = None,
        max_workers: int = 10,
        process_audio: bool = True,
        audio_language: str | None = None,
        media_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """
        Process a video using FFmpeg with Azure Batch API (50% cheaper).

        Features:
        - Ultra-fast extraction with FFmpeg (15x faster than OpenCV)
        - Frame analysis with Azure Global Batch API (50% cheaper)
        - Audio transcription with Whisper
        - No restrictive rate limits

        Args:
            blob_name: Name of the blob in Azure Storage
            config: Custom FFmpeg configuration
            preset: Predefined preset (if no config is provided)
            custom_prompt: Custom prompt for analysis
            max_workers: Maximum parallel threads (fallback)
            process_audio: If True, extracts and transcribes the video audio
            audio_language: Audio language (None for automatic detection)
            media_id: Media ID for batch job tracking
            user_id: User ID for batch job tracking

        Returns:
            Dictionary with frames_data, video_metadata, audio_data, processing_stats
        """
        # Determine configuration
        if config is None:
            if preset:
                config = get_preset_config(preset)
            else:
                config = FFmpegProcessingConfig()

        ffmpeg_proc = FFmpegVideoProcessor(config)
        metrics = PipelineMetrics(media_id=media_id or blob_name)
        metrics.pipeline_start = time.monotonic()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # 1. Download video
            metrics.start_stage("download")
            logger.info(f"Downloading video: {blob_name}")
            await self._download_blob_streaming(blob_name, tmp_path)
            metrics.end_stage("download")

            # 2. Analyze metadata
            logger.info("Analyzing video information...")
            video_info = ffmpeg_proc.get_video_info(tmp_path)

            # 3. Extract frames
            metrics.start_stage("frame_extraction")
            if settings.processing.streaming_pipeline_enabled:
                logger.info("Extracting frames with streaming pipeline...")
                frame_stream = ffmpeg_proc.extract_frames_stream(
                    video_path=tmp_path,
                )
                frame_count, frames_for_batch = await self._process_frames_streaming(
                    frame_stream,
                    settings.processing.streaming_batch_size,
                )
                # Lightweight list for downstream len() compatibility
                frames = [
                    {
                        "frame_number": fb["frame_number"],
                        "timestamp": fb.get("timestamp"),
                    }
                    for fb in frames_for_batch
                ]
                logger.info(f"{frame_count} frames extracted (streaming pipeline)")
            else:
                logger.info("Extracting frames with FFmpeg...")
                frames = ffmpeg_proc.extract_frames_ffmpeg(
                    video_path=tmp_path, return_as_bytes=True
                )
                logger.info(f"{len(frames)} frames extracted")
            resolution = f"{video_info.get('width', '?')}x{video_info.get('height', '?')}"
            metrics.end_stage(
                "frame_extraction",
                items_processed=len(frames),
                method=ffmpeg_proc._decoder_backend,
                resolution=resolution,
            )

            # 4. Submit batch job FIRST (non-blocking), then process audio
            #    during batch wait — saves 30-60s by overlapping I/O
            batch_proc = BatchProcessor(self.openai_client)
            if not settings.processing.streaming_pipeline_enabled:
                frames_for_batch = self._prepare_frames_for_batch(frames)

            logger.info(f"Submitting batch job for analysis of {len(frames)} frames")
            vision_requests = batch_proc.create_vision_batch_requests(
                frames_for_batch, custom_prompt
            )
            vision_batch_id = await batch_proc.submit_batch_job(
                vision_requests,
                description=f"Vision analysis: {blob_name} ({len(frames)} frames)",
            )
            logger.info(f"Batch job submitted: {vision_batch_id} — processing audio in parallel")

            # 5+6. Run audio transcription and batch wait concurrently
            #      using structured concurrency (TaskGroup).
            #
            # Benefits over the previous sequential approach:
            #   - If batch completes first, result retrieval and embedding
            #     generation start immediately (truly concurrent).
            #   - If batch FAILS, audio transcription is cancelled
            #     immediately — no wasted work.
            #   - Audio is wrapped in _safe_process_audio so its failure
            #     does NOT cancel the batch pipeline (non-fatal).
            async with asyncio.TaskGroup() as tg:
                audio_task = (
                    tg.create_task(
                        self._safe_process_audio(tmp_path, audio_language, metrics),
                        name="audio-transcription",
                    )
                    if process_audio
                    else None
                )
                batch_task = tg.create_task(
                    self._wait_and_finalize_batch(
                        batch_proc=batch_proc,
                        vision_batch_id=vision_batch_id,
                        frames=frames,
                        frames_for_batch=frames_for_batch,
                        video_info=video_info,
                        blob_name=blob_name,
                        ffmpeg_proc=ffmpeg_proc,
                        audio_data=None,  # merged after TaskGroup
                        pipeline_metrics=metrics,
                    ),
                    name="batch-finalize",
                )

            result = batch_task.result()
            audio_data = audio_task.result() if audio_task else None

            # Merge audio data into the combined result
            result["audio_data"] = audio_data
            result["processing_stats"]["audio_processed"] = (
                audio_data is not None and audio_data.get("stats", {}).get("has_audio", False)
            )
            if audio_data and audio_data.get("stats", {}).get("has_audio"):
                logger.info(f"Audio transcribed: {audio_data['stats']['total_words']} words")

            return result

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _prepare_frames_for_batch(self, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Prepare extracted frames for Batch API submission.

        Encodes images using the optimized encoder (WebP or JPEG, with
        resize) and estimates visual complexity for adaptive token budgets.

        Args:
            frames: Raw frames with image_data bytes.

        Returns:
            List of frame dicts with image_base64, media_type, and
            max_tokens for batch API.
        """
        frames_for_batch: list[dict[str, Any]] = []
        for frame_info in frames:
            image_bytes = frame_info["image_data"]
            image_base64, media_type = self._encode_frame_optimized(image_bytes)
            max_tokens = self._estimate_token_budget(image_bytes)
            frames_for_batch.append(
                {
                    "frame_number": frame_info["frame_number"],
                    "timestamp": frame_info.get("timestamp"),
                    "image_base64": image_base64,
                    "media_type": media_type,
                    "max_tokens": max_tokens,
                }
            )
        return frames_for_batch

    async def _process_frames_streaming(
        self,
        frame_stream: AsyncIterator[dict[str, Any]],
        batch_size: int = 32,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Consume a streaming frame iterator in configurable batches.

        Collects frames into batches of *batch_size*, prepares each batch
        (base64 encoding + complexity estimation) via
        :pymethod:`_prepare_frames_for_batch`, then releases the raw bytes
        before collecting the next batch.  This reduces peak memory from
        ``O(all_frames)`` to ``O(batch_size)`` during the preparation
        phase.

        Args:
            frame_stream: Async iterator yielding frame dicts with
                ``image_data`` bytes.
            batch_size: Number of frames per processing batch.

        Returns:
            Tuple of ``(total_frame_count, prepared_frames_for_batch)``
            where *prepared_frames_for_batch* is the full list of frame
            dicts ready for batch API submission.
        """
        all_prepared: list[dict[str, Any]] = []
        batch: list[dict[str, Any]] = []
        total_count = 0
        peak_batch_bytes = 0

        async for frame in frame_stream:
            batch.append(frame)
            total_count += 1

            if len(batch) >= batch_size:
                batch_bytes = sum(len(f.get("image_data", b"")) for f in batch)
                peak_batch_bytes = max(peak_batch_bytes, batch_bytes)

                prepared = self._prepare_frames_for_batch(batch)
                all_prepared.extend(prepared)
                batch = []  # release raw image_data bytes
                logger.debug(
                    "Streaming batch processed: %d frames prepared so far " "(batch %.1f MB)",
                    len(all_prepared),
                    batch_bytes / (1024 * 1024),
                )

        # Flush remaining frames
        if batch:
            batch_bytes = sum(len(f.get("image_data", b"")) for f in batch)
            peak_batch_bytes = max(peak_batch_bytes, batch_bytes)
            prepared = self._prepare_frames_for_batch(batch)
            all_prepared.extend(prepared)
            batch = []

        logger.info(
            "Streaming pipeline complete: %d frames, " "peak batch memory ≈ %.1f MB",
            total_count,
            peak_batch_bytes / (1024 * 1024),
        )

        return total_count, all_prepared

    def _estimate_token_budget(self, image_bytes: bytes) -> int:
        """Estimate token budget based on image entropy (visual complexity)."""
        try:
            img_array = np.frombuffer(image_bytes, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return self.TOKEN_BUDGET["high"]

            histogram = cv2.calcHist([img], [0], None, [256], [0, 256]).flatten()
            histogram = histogram[histogram > 0] / histogram.sum()
            entropy = -np.sum(histogram * np.log2(histogram))

            if entropy < self.COMPLEXITY_LOW_THRESHOLD:
                return self.TOKEN_BUDGET["low"]
            elif entropy < self.COMPLEXITY_HIGH_THRESHOLD:
                return self.TOKEN_BUDGET["medium"]
            else:
                return self.TOKEN_BUDGET["high"]
        except Exception:
            return self.TOKEN_BUDGET["high"]

    async def _wait_and_finalize_batch(
        self,
        batch_proc: "BatchProcessor",
        vision_batch_id: str,
        frames: list[dict[str, Any]],
        frames_for_batch: list[dict[str, Any]],
        video_info: dict[str, Any],
        blob_name: str,
        ffmpeg_proc: FFmpegVideoProcessor,
        audio_data: dict[str, Any] | None = None,
        pipeline_metrics: PipelineMetrics | None = None,
    ) -> dict[str, Any]:
        """
        Wait for batch completion and finalize results with embeddings.

        This method is called after the batch job has been submitted and audio
        processing has completed (or been skipped). The batch may already be
        done by this point if audio processing took a while.

        Args:
            batch_proc: BatchProcessor instance.
            vision_batch_id: ID of the submitted batch job.
            frames: Original extracted frames.
            frames_for_batch: Prepared frames with base64 data.
            video_info: Video metadata.
            blob_name: Azure blob name.
            ffmpeg_proc: FFmpeg processor for status.
            audio_data: Processed audio data (optional).

        Returns:
            Combined processing results dict.
        """
        logger.info(f"Waiting for analysis completion (batch: {vision_batch_id})")

        if pipeline_metrics:
            pipeline_metrics.start_stage("vision_analysis")
        start_analysis = time.time()
        success = await batch_proc.wait_for_batch_completion(
            vision_batch_id,
            check_interval=self.BATCH_CHECK_INTERVAL_SECONDS,
            max_wait_time=self.BATCH_MAX_WAIT_TIME_SECONDS,
        )
        analysis_time = time.time() - start_analysis

        if not success:
            if pipeline_metrics:
                pipeline_metrics.end_stage("vision_analysis", items_failed=len(frames))
            raise RuntimeError(f"Batch analysis failed or timed out: {vision_batch_id}")

        logger.info(f"Analysis completed in {analysis_time:.2f}s")

        # 4. Retrieve and parse analysis results
        logger.info("Retrieving analysis results")
        vision_results = await batch_proc.get_batch_results(vision_batch_id)
        parsed_analyses = batch_proc.parse_vision_results(vision_results)
        analyzed_count = sum(1 for v in parsed_analyses.values() if v.get("success"))
        failed_count = len(frames) - analyzed_count
        if pipeline_metrics:
            pipeline_metrics.end_stage(
                "vision_analysis",
                items_processed=analyzed_count,
                items_failed=failed_count,
                batch_id=vision_batch_id,
            )

        # 5. Prepare texts for embeddings
        logger.info("Preparing texts for batch embeddings")
        texts_to_embed: list[str] = []
        frame_to_text_idx: dict[int, int] = {}

        for frame_data in frames_for_batch:
            custom_id = f"frame_{frame_data['frame_number']}"
            analysis_data = parsed_analyses.get(custom_id, {})

            if analysis_data.get("success") and analysis_data.get("analysis"):
                frame_to_text_idx[frame_data["frame_number"]] = len(texts_to_embed)
                texts_to_embed.append(analysis_data["analysis"])

        logger.info(f"{len(texts_to_embed)}/{len(frames)} frames with valid analysis")

        # 6. Generate embeddings in standard mode (Batch API does not support /embeddings)
        embeddings_dict: dict[str, list[float]] = {}
        if texts_to_embed:
            if pipeline_metrics:
                pipeline_metrics.start_stage("embedding")
            logger.info("Generating embeddings in parallel")
            start_embeddings = time.time()

            all_embeddings = await self.generate_embeddings_batch(texts_to_embed)

            embeddings_time = time.time() - start_embeddings
            logger.info(f"Embeddings generated in {embeddings_time:.2f}s")
            if pipeline_metrics:
                pipeline_metrics.end_stage("embedding", items_processed=len(all_embeddings))

            # Build embeddings dictionary
            for idx, embedding in enumerate(all_embeddings):
                embeddings_dict[f"embedding_{idx}"] = embedding
        else:
            embeddings_time = 0.0

        # 8. Combine results
        logger.info("Combining results")
        frames_data: list[dict[str, Any]] = []
        tokens_total = 0

        for frame_data in frames_for_batch:
            frame_number = frame_data["frame_number"]
            custom_id = f"frame_{frame_number}"
            analysis_data = parsed_analyses.get(custom_id, {})

            # Retrieve embedding if available
            embedding: list[float] = []
            if frame_number in frame_to_text_idx:
                text_idx = frame_to_text_idx[frame_number]
                embedding_id = f"embedding_{text_idx}"
                embedding = embeddings_dict.get(embedding_id, [])

            frame_result = {
                "frame_number": frame_number,
                "timestamp": frame_data.get("timestamp"),
                "analysis": analysis_data.get("analysis"),
                "analysis_structured": analysis_data.get("analysis_structured"),
                "tokens_used": analysis_data.get("tokens_used", 0),
                "embedding": embedding,
                "embedding_coarse": embedding[:512] if len(embedding) >= 512 else embedding,
            }

            frames_data.append(frame_result)
            tokens_total += frame_result["tokens_used"]

        # 9. Calculate final stats
        total_time = analysis_time + embeddings_time
        status = ffmpeg_proc.get_status()
        pipeline = ffmpeg_proc.get_processing_pipeline()

        # Finalize pipeline metrics
        if pipeline_metrics:
            pipeline_metrics.pipeline_end = time.monotonic()

        result = {
            "video_metadata": video_info,
            "frames_data": frames_data,
            "audio_data": audio_data,
            "processing_stats": {
                "frames_extracted": len(frames),
                "frames_analyzed": len([f for f in frames_data if f.get("analysis")]),
                "frames_with_embeddings": len([f for f in frames_data if f.get("embedding")]),
                "tokens_total": tokens_total,
                "extraction_fps": status.fps,
                "analysis_time_seconds": analysis_time,
                "embeddings_time_seconds": embeddings_time,
                "total_processing_time": total_time,
                "processing_mode": "batch_api",
                "cost_savings": "50% vs regular API",
                "vision_batch_id": vision_batch_id,
                "audio_processed": audio_data is not None
                and audio_data.get("stats", {}).get("has_audio", False),
                "pipeline_metrics": pipeline_metrics.to_dict() if pipeline_metrics else None,
            },
            "status": status.dict(),
            "pipeline": pipeline.dict(),
        }

        frames_with_embeddings = len([f for f in frames_data if f.get("embedding")])
        logger.info(
            f"Batch completed: {len(frames)} frames in {total_time:.2f}s, "
            f"{frames_with_embeddings} embeddings, 50%% savings"
        )
        if audio_data and audio_data.get("stats", {}).get("has_audio"):
            logger.info(f"Audio transcribed: {audio_data['stats']['total_words']} words")

        if pipeline_metrics:
            pipeline_metrics.log_summary()

        return result

    def get_processing_pipeline_preview(
        self, config: FFmpegProcessingConfig | None = None, preset: ProcessingPreset | None = None
    ) -> ProcessingPipeline:
        """
        Get a preview of the processing pipeline without executing it.

        Args:
            config: Custom FFmpeg configuration
            preset: Predefined preset

        Returns:
            ProcessingPipeline for visualization
        """
        if config is None:
            if preset:
                config = get_preset_config(preset)
            else:
                config = FFmpegProcessingConfig()

        processor = FFmpegVideoProcessor(config)
        return processor.get_processing_pipeline()
