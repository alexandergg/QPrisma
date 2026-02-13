"""
Audio Processing Service
Extracts audio from videos, transcribes with Whisper, and generates enriched analysis.
Supports chunking for large files (>25MB Azure Whisper limit).
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any

from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError

logger = logging.getLogger(__name__)

# Azure Whisper has a 25MB limit
WHISPER_MAX_FILE_SIZE_MB = 25
# Target chunk duration for audio (5 minutes gives ~5-8MB at mp3 128kbps)
CHUNK_DURATION_SECONDS = 300  # 5 minutes
# VAD silence detection defaults
VAD_NOISE_THRESHOLD_DB = -30  # dB threshold for silence detection
VAD_MIN_SILENCE_DURATION = 0.5  # minimum silence gap in seconds


class AudioProcessor:
    """
    Processes video audio: extraction, transcription with Whisper, analysis.

    Attributes:
        openai_client: Azure OpenAI client for Whisper and GPT.
        whisper_deployment: Name of the Whisper deployment.
        gpt_deployment: Name of the GPT deployment.
        rate_limit_rpm: Requests-per-minute limit for Whisper.
    """

    def __init__(self, openai_client: AzureOpenAI | AsyncAzureOpenAI, rate_limit_rpm: int = 3):
        self.openai_client = openai_client
        self.whisper_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_WHISPER", "whisper")
        self.gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")
        self.rate_limit_rpm = rate_limit_rpm
        self._last_request_time = 0.0

    async def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect the rate limit."""
        if self.rate_limit_rpm <= 0:
            return

        min_interval = 60.0 / self.rate_limit_rpm
        elapsed = time.time() - self._last_request_time

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"Rate limit: waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

        self._last_request_time = time.time()

    def extract_audio_from_video(
        self,
        video_path: str,
        output_path: str | None = None,
        audio_format: str = "mp3",
        audio_bitrate: str = "128k",
    ) -> str:
        """
        Extract audio from a video using FFmpeg.

        Args:
            video_path: Path to the video
            output_path: Output path (if None, creates a temp file)
            audio_format: Audio format (mp3, wav, m4a)
            audio_bitrate: Audio bitrate

        Returns:
            Path to the extracted audio file
        """
        if output_path is None:
            output_path = tempfile.mktemp(suffix=f".{audio_format}")

        # FFmpeg command to extract audio
        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-vn",  # No video
            "-acodec",
            "libmp3lame" if audio_format == "mp3" else "copy",
            "-ab",
            audio_bitrate,
            "-ar",
            "16000",  # 16kHz is optimal for Whisper
            "-ac",
            "1",  # Mono
            "-y",  # Overwrite
            output_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Audio extracted: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error extracting audio: {e.stderr}")

    def get_audio_duration(self, audio_path: str) -> float:
        """
        Get the audio duration in seconds using ffprobe.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Duration in seconds, or 0.0 on error.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error getting audio duration: {e}")
            return 0.0
        except ValueError as e:
            logger.warning(f"Error parsing audio duration: {e}")
            return 0.0

    def _detect_silence_boundaries(
        self,
        audio_path: str,
        noise_db: float = VAD_NOISE_THRESHOLD_DB,
        min_silence: float = VAD_MIN_SILENCE_DURATION,
    ) -> list[dict[str, float]]:
        """
        Detect silence gaps in audio using FFmpeg silencedetect filter.

        Returns list of silence intervals: [{"start": float, "end": float}, ...]
        """
        cmd = [
            "ffmpeg",
            "-i",
            audio_path,
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f",
            "null",
            "-",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            stderr = result.stderr

            starts = re.findall(r"silence_start: ([\d.]+)", stderr)
            ends = re.findall(r"silence_end: ([\d.]+)", stderr)

            silences = []
            for i in range(min(len(starts), len(ends))):
                silences.append(
                    {
                        "start": float(starts[i]),
                        "end": float(ends[i]),
                    }
                )
            return silences

        except Exception as e:
            logger.warning(f"Silence detection failed, falling back to fixed chunking: {e}")
            return []

    def _find_vad_split_points(
        self,
        total_duration: float,
        silences: list[dict[str, float]],
        target_chunk: float = CHUNK_DURATION_SECONDS,
        min_chunk: float = 60.0,
    ) -> list[float]:
        """
        Find optimal split points at silence boundaries near target chunk durations.

        Args:
            total_duration: Total audio duration in seconds.
            silences: Silence intervals from _detect_silence_boundaries.
            target_chunk: Target chunk duration (default 300s).
            min_chunk: Minimum chunk size to prevent tiny fragments.

        Returns:
            List of split timestamps (excluding 0 and total_duration).
        """
        if not silences or total_duration <= target_chunk:
            return []

        split_points = []
        current_start = 0.0

        while current_start + target_chunk < total_duration:
            target_time = current_start + target_chunk
            # Search window: 80%-120% of target chunk boundary
            window_start = current_start + target_chunk * 0.8
            window_end = min(current_start + target_chunk * 1.2, total_duration)

            # Find the silence gap closest to the target within the window
            best_split = None
            best_distance = float("inf")

            for silence in silences:
                midpoint = (silence["start"] + silence["end"]) / 2
                if window_start <= midpoint <= window_end:
                    distance = abs(midpoint - target_time)
                    if distance < best_distance:
                        best_distance = distance
                        best_split = midpoint

            if best_split and (best_split - current_start) >= min_chunk:
                split_points.append(best_split)
                current_start = best_split
            else:
                # No silence found in window — fall back to target time
                split_points.append(target_time)
                current_start = target_time

        return split_points

    def split_audio_into_chunks(
        self,
        audio_path: str,
        chunk_duration: float = CHUNK_DURATION_SECONDS,
        output_dir: str | None = None,
        use_vad: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Divide audio into chunks using VAD-based silence detection for natural boundaries.

        Falls back to fixed-duration chunking if VAD detection fails.

        Args:
            audio_path: Path to the audio file.
            chunk_duration: Maximum duration of each chunk in seconds.
            output_dir: Directory for chunks (temporary if None).
            use_vad: Whether to use Voice Activity Detection for smart boundaries.

        Returns:
            List of dicts with info for each chunk: {path, start_time, end_time, index}.
        """
        total_duration = self.get_audio_duration(audio_path)
        if total_duration <= 0:
            return [{"path": audio_path, "start_time": 0, "end_time": 0, "index": 0}]

        # Check if chunking is needed
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        if file_size_mb <= WHISPER_MAX_FILE_SIZE_MB and total_duration <= chunk_duration:
            logger.info(f"Small audio ({file_size_mb:.1f}MB), chunking not required")
            return [{"path": audio_path, "start_time": 0, "end_time": total_duration, "index": 0}]

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="audio_chunks_")

        # Determine split points using VAD or fixed intervals
        if use_vad:
            silences = self._detect_silence_boundaries(audio_path)
            split_points = self._find_vad_split_points(
                total_duration, silences, target_chunk=chunk_duration
            )
            if split_points:
                logger.info(
                    f"VAD: found {len(split_points)} silence-based split points "
                    f"for {total_duration:.1f}s audio"
                )
            else:
                logger.info("VAD: no split points found, using fixed intervals")
        else:
            split_points = []

        # Build chunk boundaries from split points
        boundaries = [0.0] + split_points + [total_duration]
        # If no VAD splits, fall back to fixed-duration boundaries
        if len(boundaries) == 2 and total_duration > chunk_duration:
            boundaries = [0.0]
            t = chunk_duration
            while t < total_duration:
                boundaries.append(t)
                t += chunk_duration
            boundaries.append(total_duration)

        chunks: list[dict[str, Any]] = []
        logger.info(
            f"Splitting {total_duration:.1f}s audio into {len(boundaries) - 1} chunks "
            f"({'VAD' if split_points else 'fixed'})"
        )

        for chunk_index in range(len(boundaries) - 1):
            current_time = boundaries[chunk_index]
            end_time = boundaries[chunk_index + 1]
            chunk_path = os.path.join(output_dir, f"chunk_{chunk_index:03d}.mp3")

            cmd = [
                "ffmpeg",
                "-i",
                audio_path,
                "-ss",
                str(current_time),
                "-t",
                str(end_time - current_time),
                "-acodec",
                "libmp3lame",
                "-ab",
                "128k",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                chunk_path,
            ]

            try:
                subprocess.run(cmd, capture_output=True, check=True)
                chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                logger.debug(
                    f"Chunk {chunk_index}: {current_time:.1f}s - {end_time:.1f}s ({chunk_size_mb:.1f}MB)"
                )

                chunks.append(
                    {
                        "path": chunk_path,
                        "start_time": current_time,
                        "end_time": end_time,
                        "index": chunk_index,
                        "size_mb": chunk_size_mb,
                    }
                )

            except subprocess.CalledProcessError as e:
                logger.warning(f"Error creating chunk {chunk_index}: {e}")

        logger.info(f"Created {len(chunks)} chunks")
        return chunks

    async def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Transcribe audio using Azure OpenAI Whisper.

        For large files, automatically splits into chunks.

        Args:
            audio_path: Path to the audio file.
            language: Language code (es, en, etc.) - None for automatic detection.
            response_format: Response format (json, text, srt, verbose_json, vtt).
            timestamp_granularities: Timestamp granularity ["word", "segment"].

        Returns:
            Dictionary with transcription and metadata.
        """
        logger.info("Transcribing audio with Whisper")

        if timestamp_granularities is None:
            timestamp_granularities = ["segment", "word"]

        # Check size and decide whether to chunk
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        audio_duration = self.get_audio_duration(audio_path)

        logger.info(f"Size: {file_size_mb:.1f}MB, Duration: {audio_duration:.1f}s")

        if file_size_mb > WHISPER_MAX_FILE_SIZE_MB:
            logger.info(f"File exceeds {WHISPER_MAX_FILE_SIZE_MB}MB, using chunking")
            return await self._transcribe_with_chunking(
                audio_path, language, response_format, timestamp_granularities
            )

        # Direct transcription for small files
        return await self._transcribe_single_file(
            audio_path, language, response_format, timestamp_granularities, time_offset=0
        )

    async def _transcribe_single_file(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
        time_offset: float = 0,
    ) -> dict[str, Any]:
        """
        Transcribe a single audio file.

        Args:
            audio_path: Path to the audio file.
            language: Language code (optional).
            response_format: Response format.
            timestamp_granularities: Timestamp granularity.
            time_offset: Time offset to adjust timestamps.

        Returns:
            Dictionary with transcription results.
        """
        await self._wait_for_rate_limit()

        try:
            with open(audio_path, "rb") as audio_file:
                start_time = time.time()

                transcription = await self.openai_client.audio.transcriptions.create(
                    model=self.whisper_deployment,
                    file=audio_file,
                    language=language,
                    response_format=response_format,
                    timestamp_granularities=timestamp_granularities,
                )

                elapsed = time.time() - start_time

                # Convert to dict
                if hasattr(transcription, "model_dump"):
                    result = transcription.model_dump()
                elif hasattr(transcription, "to_dict"):
                    result = transcription.to_dict()
                else:
                    result = dict(transcription)

                # Adjust timestamps if there is an offset
                if time_offset > 0:
                    result = self._adjust_timestamps(result, time_offset)

                logger.info(f"Transcription completed in {elapsed:.2f}s")
                return result

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error in transcription: {e}")
            raise
        except OSError as e:
            logger.error(f"File error in transcription: {e}")
            raise

    async def _transcribe_with_chunking(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
    ) -> dict[str, Any]:
        """
        Transcribe large audio by splitting it into chunks.

        Args:
            audio_path: Path to the audio file.
            language: Language code (optional).
            response_format: Response format.
            timestamp_granularities: Timestamp granularity.

        Returns:
            Dictionary with combined transcription results.
        """
        chunks = self.split_audio_into_chunks(audio_path)

        all_segments: list[dict[str, Any]] = []
        all_words: list[dict[str, Any]] = []
        full_text_parts: list[str] = []
        detected_language: str | None = None
        total_duration = 0.0

        logger.info(f"Processing {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            logger.debug(
                f"Chunk {i+1}/{len(chunks)}: {chunk['start_time']:.1f}s - {chunk['end_time']:.1f}s"
            )

            try:
                result = await self._transcribe_single_file(
                    chunk["path"],
                    language,
                    response_format,
                    timestamp_granularities,
                    time_offset=chunk["start_time"],
                )

                # Accumulate results
                if result.get("text"):
                    full_text_parts.append(result["text"])

                if result.get("segments"):
                    all_segments.extend(result["segments"])

                if result.get("words"):
                    all_words.extend(result["words"])

                if not detected_language and result.get("language"):
                    detected_language = result["language"]

                chunk_duration = result.get("duration", chunk["end_time"] - chunk["start_time"])
                total_duration = max(total_duration, chunk["start_time"] + chunk_duration)

                logger.debug(
                    f"Chunk {i+1}: {len(result.get('text', ''))} chars, {len(result.get('segments', []))} segments"
                )

            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.error(f"OpenAI API error in chunk {i}: {e}")
                continue
            except Exception as e:
                logger.exception(f"Unexpected error in chunk {i}: {e}")
                continue
            finally:
                # Clean up temporary chunk
                if chunk.get("path") != audio_path and os.path.exists(chunk["path"]):
                    try:
                        os.unlink(chunk["path"])
                    except OSError:
                        pass

        # Combine results
        combined_result: dict[str, Any] = {
            "text": " ".join(full_text_parts),
            "language": detected_language,
            "duration": total_duration,
            "segments": all_segments,
            "words": all_words,
            "chunked": True,
            "chunk_count": len(chunks),
        }

        logger.info(
            f"Combined transcription completed: {len(combined_result['text'])} chars, "
            f"{len(all_segments)} segments, {len(all_words)} words"
        )

        return combined_result

    def _adjust_timestamps(self, result: dict[str, Any], offset: float) -> dict[str, Any]:
        """
        Adjust all timestamps by adding an offset.

        Args:
            result: Dictionary with transcription results.
            offset: Offset in seconds to add to the timestamps.

        Returns:
            Dictionary with adjusted timestamps.
        """
        # Adjust segments
        if "segments" in result:
            for segment in result["segments"]:
                if "start" in segment:
                    segment["start"] += offset
                if "end" in segment:
                    segment["end"] += offset

        # Adjust words
        if "words" in result:
            for word in result["words"]:
                if "start" in word:
                    word["start"] += offset
                if "end" in word:
                    word["end"] += offset

        return result

    async def analyze_transcription(
        self, transcription_text: str, video_descriptions: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Analyze the transcription to extract insights using GPT-4.

        Args:
            transcription_text: Transcription text.
            video_descriptions: Visual descriptions of frames (optional).

        Returns:
            Dictionary with enriched analysis.
        """
        logger.info("Analyzing transcription with GPT-4o")

        # Build context with visual descriptions if available
        context = ""
        if video_descriptions:
            context = "\n\nVISUAL CONTEXT:\n"
            for i, desc in enumerate(video_descriptions[:10], 1):  # First 10 frames
                context += f"Frame {i}: {desc}\n"

        prompt = f"""Analyze this video transcription and provide a structured JSON analysis with:

1. **summary**: Executive summary (2-3 sentences)
2. **main_topics**: List of key topics mentioned
3. **entities**: People, places, organizations mentioned
4. **sentiment**: Sentiment analysis (positive/neutral/negative/mixed)
5. **key_moments**: Important timestamps with description
6. **keywords**: Search keywords (10-15 terms)
7. **category**: Content category (educational, entertainment, news, etc.)
8. **language**: Primary detected language
9. **estimated_duration**: Approximate duration in seconds
{context}

TRANSCRIPTION:
{transcription_text}

Respond ONLY with valid JSON, without markdown or additional explanations."""

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.gpt_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in multimedia content analysis. You respond ONLY with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1,
                response_format={"type": "json_object"},
            )

            analysis = json.loads(response.choices[0].message.content)

            logger.info(
                f"Analysis completed: {analysis.get('summary', 'N/A')[:50]}..., "
                f"topics: {len(analysis.get('main_topics', []))}"
            )

            return analysis

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error analyzing transcription: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing analysis JSON: {e}")
            return {}
        except Exception as e:
            logger.exception(f"Unexpected error analyzing transcription: {e}")
            return {}

    async def process_video_audio(
        self,
        video_path: str,
        language: str | None = None,
        video_descriptions: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Full pipeline: extracts audio, transcribes, and analyzes.

        Args:
            video_path: Path to the video.
            language: Language (None for automatic detection).
            video_descriptions: Frame descriptions for context.

        Returns:
            Complete dictionary with transcription and analysis.
        """
        audio_path: str | None = None

        try:
            # 1. Extract audio
            logger.info("Starting audio processing")

            audio_path = self.extract_audio_from_video(video_path)

            # 2. Transcribe
            transcription = await self.transcribe_audio(audio_path, language=language)

            # 3. Analyze transcription
            full_text = transcription.get("text", "")
            analysis: dict[str, Any] = {}

            if full_text and len(full_text.strip()) > 50:
                analysis = await self.analyze_transcription(full_text, video_descriptions)
            else:
                logger.warning("Transcription too short or empty, skipping analysis")

            # 4. Consolidate result
            result: dict[str, Any] = {
                "transcription": {
                    "text": full_text,
                    "language": transcription.get("language"),
                    "duration": transcription.get("duration"),
                    "segments": transcription.get("segments", []),
                    "words": transcription.get("words", []),
                },
                "analysis": analysis,
                "stats": {
                    "total_words": len(full_text.split()) if full_text else 0,
                    "total_segments": len(transcription.get("segments", [])),
                    "has_audio": len(full_text.strip()) > 0,
                    "audio_duration": transcription.get("duration", 0),
                },
            }

            logger.info(
                f"Audio processing completed: {len(full_text)} chars, "
                f"{result['stats']['total_words']} words, {result['stats']['total_segments']} segments"
            )

            return result

        except (subprocess.SubprocessError, RuntimeError) as e:
            logger.error(f"Process error processing audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }
        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error processing audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }
        except Exception as e:
            logger.exception(f"Unexpected error processing audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }

        finally:
            # Clean up temporary file
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass
