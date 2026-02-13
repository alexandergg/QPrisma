"""
Video Processing Service
Extracts frames from videos, analyzes them with GPT-4o Vision, and generates embeddings.
Uses ultra-fast FFmpeg and Azure OpenAI Batch API (50% cheaper).
"""

import base64
import logging
import os
import subprocess
import tempfile
import time
from typing import Any

import cv2
import numpy as np
from azure.storage.blob import BlobServiceClient
from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError

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
    EMBEDDING_BATCH_SIZE = 16
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

    def extract_frames(
        self, video_path: str, max_frames: int = 10, interval_seconds: float | None = None
    ) -> list[np.ndarray]:
        """
        Extract frames from a video.

        Args:
            video_path: Path to the video file
            max_frames: Maximum number of frames to extract
            interval_seconds: Interval between frames (if None, distributes evenly)

        Returns:
            List of frames as numpy arrays
        """
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        # Get video information
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        _duration = total_frames / fps if fps > 0 else 0

        frames = []

        if interval_seconds:
            # Extract frames at specific intervals
            frame_interval = int(interval_seconds * fps)
            frame_positions = range(0, total_frames, frame_interval)[:max_frames]
        else:
            # Distribute frames evenly
            if total_frames <= max_frames:
                frame_positions = range(total_frames)
            else:
                step = total_frames / max_frames
                frame_positions = [int(i * step) for i in range(max_frames)]

        for frame_pos in frame_positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()

            if ret:
                frames.append(frame)

            if len(frames) >= max_frames:
                break

        cap.release()

        return frames

    def frame_to_base64(self, frame: np.ndarray, quality: int = 85) -> str:
        """Convert a numpy frame to base64 JPEG."""
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    async def analyze_frame_with_gpt4v(
        self,
        frame: np.ndarray,
        custom_prompt: str | None = None,
        detail_level: str = "auto",
        *,
        timestamp: float | int | None = None,
        max_tokens: int = 900,
    ) -> dict:
        """
        Analyze a frame with GPT-4o Vision.

        Args:
            frame: Frame as a numpy array
            custom_prompt: Custom prompt (optional)
            detail_level: "low", "high" or "auto"

        Returns:
            Dictionary with the frame analysis
        """
        # Convert frame to base64
        base64_image = self.frame_to_base64(frame)

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
                                    "url": f"data:image/jpeg;base64,{base64_image}",
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
        self, texts: list[str], batch_size: int = 16
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.

        Azure OpenAI supports up to 2048 texts per request; we use batches of 16 for safety.

        Args:
            texts: List of texts to convert into embeddings.
            batch_size: Batch size for each request.

        Returns:
            List of embeddings, one per input text.
        """
        if not texts:
            logger.warning("generate_embeddings_batch: empty text list")
            return []

        logger.info(f"Generating embeddings for {len(texts)} texts in batches of {batch_size}")
        embeddings: list[list[float]] = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_num = i // batch_size + 1

            try:
                logger.debug(f"Processing batch {batch_num}/{total_batches} ({len(batch)} texts)")

                response = await self.openai_client.embeddings.create(
                    model=self.embedding_deployment, input=batch
                )

                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)

                logger.debug(
                    f"Batch {batch_num}/{total_batches}: {len(batch_embeddings)} embeddings generated"
                )

            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.error(f"OpenAI API error in batch {batch_num}/{total_batches}: {e}")
                embeddings.extend([[] for _ in batch])
            except Exception as e:
                logger.exception(f"Unexpected error in batch {batch_num}/{total_batches}: {e}")
                embeddings.extend([[] for _ in batch])

        logger.info(f"Total: {len(embeddings)} embeddings generated")
        return embeddings

    # =========================================================================
    # PROCESSING WITH FFMPEG + BATCH API
    # =========================================================================

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

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # 1. Download video
            logger.info(f"Downloading video: {blob_name}")
            await self._download_blob_streaming(blob_name, tmp_path)

            # 2. Analyze metadata
            logger.info("Analyzing video information...")
            video_info = ffmpeg_proc.get_video_info(tmp_path)

            # 3. Extract frames
            logger.info("Extracting frames with FFmpeg...")
            frames = ffmpeg_proc.extract_frames_ffmpeg(video_path=tmp_path, return_as_bytes=True)
            logger.info(f"{len(frames)} frames extracted")

            # 4. Submit batch job FIRST (non-blocking), then process audio
            #    during batch wait — saves 30-60s by overlapping I/O
            batch_proc = BatchProcessor(self.openai_client)
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

            # 5. Process audio DURING batch wait (overlapping I/O)
            audio_data = None
            if process_audio:
                try:
                    logger.info("Processing audio while batch API analyzes frames...")
                    audio_data = await self.audio_processor.process_video_audio(
                        video_path=tmp_path,
                        language=audio_language,
                        video_descriptions=None,
                    )
                except (OSError, subprocess.SubprocessError) as e:
                    logger.warning(f"Error processing audio (continuing without audio): {e}")
                    audio_data = None
                except Exception as e:
                    logger.warning(f"Unexpected error processing audio: {e}")
                    audio_data = None

            # 6. Now wait for batch completion (may already be done if audio was slow)
            return await self._wait_and_finalize_batch(
                batch_proc=batch_proc,
                vision_batch_id=vision_batch_id,
                frames=frames,
                frames_for_batch=frames_for_batch,
                video_info=video_info,
                blob_name=blob_name,
                ffmpeg_proc=ffmpeg_proc,
                audio_data=audio_data,
            )

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _prepare_frames_for_batch(self, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Prepare extracted frames for Batch API submission.

        Encodes images to base64 and estimates visual complexity for
        adaptive token budgets.

        Args:
            frames: Raw frames with image_data bytes.

        Returns:
            List of frame dicts with image_base64 and max_tokens for batch API.
        """
        frames_for_batch: list[dict[str, Any]] = []
        for frame_info in frames:
            image_bytes = frame_info["image_data"]
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            max_tokens = self._estimate_token_budget(image_bytes)
            frames_for_batch.append(
                {
                    "frame_number": frame_info["frame_number"],
                    "timestamp": frame_info.get("timestamp"),
                    "image_base64": image_base64,
                    "max_tokens": max_tokens,
                }
            )
        return frames_for_batch

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

        start_analysis = time.time()
        success = await batch_proc.wait_for_batch_completion(
            vision_batch_id,
            check_interval=self.BATCH_CHECK_INTERVAL_SECONDS,
            max_wait_time=self.BATCH_MAX_WAIT_TIME_SECONDS,
        )
        analysis_time = time.time() - start_analysis

        if not success:
            raise RuntimeError(f"Batch analysis failed or timed out: {vision_batch_id}")

        logger.info(f"Analysis completed in {analysis_time:.2f}s")

        # 4. Retrieve and parse analysis results
        logger.info("Retrieving analysis results")
        vision_results = await batch_proc.get_batch_results(vision_batch_id)
        parsed_analyses = batch_proc.parse_vision_results(vision_results)

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
            logger.info("Generating embeddings in parallel")
            start_embeddings = time.time()

            all_embeddings: list[list[float]] = []

            for i in range(0, len(texts_to_embed), self.EMBEDDING_BATCH_SIZE):
                batch_texts = texts_to_embed[i : i + self.EMBEDDING_BATCH_SIZE]
                try:
                    response = await self.openai_client.embeddings.create(
                        input=batch_texts, model=self.embedding_deployment
                    )
                    batch_embeddings = [item.embedding for item in response.data]
                    all_embeddings.extend(batch_embeddings)
                    logger.debug(
                        f"{len(all_embeddings)}/{len(texts_to_embed)} embeddings generated"
                    )
                except (APIError, APIConnectionError, RateLimitError) as e:
                    logger.error(
                        f"OpenAI API error in batch {i//self.EMBEDDING_BATCH_SIZE + 1}: {e}"
                    )
                    all_embeddings.extend([[] for _ in range(len(batch_texts))])
                except Exception as e:
                    logger.exception(
                        f"Unexpected error in batch {i//self.EMBEDDING_BATCH_SIZE + 1}: {e}"
                    )
                    all_embeddings.extend([[] for _ in range(len(batch_texts))])

            embeddings_time = time.time() - start_embeddings
            logger.info(f"Embeddings generated in {embeddings_time:.2f}s")

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
