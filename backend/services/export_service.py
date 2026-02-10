"""
Export Service
==============

Service for exporting video clips with FFmpeg.
Handles cutting, cropping, subtitle burning, and format conversion.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from azure.storage.blob import BlobServiceClient, ContentSettings

from models.export_config import (
    PLATFORM_PRESETS,
    QUALITY_PRESETS,
    CropMode,
    ExportPlatform,
    ExportProgress,
    ExportQuality,
    PlatformPreset,
    QualityPreset,
    calculate_target_dimensions,
    get_platform_preset,
    get_quality_preset,
)
from services.database_service import get_database_service
from services.subtitle_service import get_subtitle_service

logger = logging.getLogger(__name__)


class ExportService:
    """
    Service for exporting video clips with FFmpeg.

    Features:
    - Cut video segments
    - Apply aspect ratio conversion (crop, letterbox, blur fill)
    - Burn subtitles (ASS format)
    - Encode for specific platforms (TikTok, Reels, Shorts, YouTube, Twitter)
    - Upload to Azure Blob Storage
    """

    def __init__(self):
        self.db = get_database_service()
        self.subtitle_service = get_subtitle_service()
        self._blob_service: BlobServiceClient | None = None
        self._container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")
        self._exports_folder = "exports"  # Subfolder in container for exports

    @property
    def blob_service(self) -> BlobServiceClient | None:
        """Lazy-load blob service client."""
        if self._blob_service is None:
            conn_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            if conn_string:
                self._blob_service = BlobServiceClient.from_connection_string(conn_string)
        return self._blob_service

    def _get_video_info(self, video_path: str) -> dict[str, Any]:
        """Get video information using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            video_stream = None
            audio_stream = None

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and video_stream is None:
                    video_stream = stream
                elif stream.get("codec_type") == "audio" and audio_stream is None:
                    audio_stream = stream

            # Parse FPS safely using Fraction instead of eval()
            fps = 30.0
            if video_stream:
                try:
                    fps_str = video_stream.get("r_frame_rate", "30/1")
                    fps = float(Fraction(fps_str))
                except (ValueError, ZeroDivisionError):
                    logger.warning(f"Invalid FPS value: {fps_str}, using default 30")
                    fps = 30.0

            return {
                "duration": float(data.get("format", {}).get("duration", 0)),
                "width": video_stream.get("width", 0) if video_stream else 0,
                "height": video_stream.get("height", 0) if video_stream else 0,
                "fps": fps,
                "codec": video_stream.get("codec_name", "") if video_stream else "",
                "has_audio": audio_stream is not None,
                "audio_codec": audio_stream.get("codec_name", "") if audio_stream else None,
            }
        except subprocess.CalledProcessError as e:
            logger.error(f"FFprobe process error: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing video info JSON: {e}")
            return {}
        except (OSError, ValueError) as e:
            logger.error(f"Error getting video info: {e}")
            return {}

    def clip_video(self, input_path: str, output_path: str, config: Any) -> None:
        """Legacy clip helper used by tests."""
        if not os.path.exists(input_path):
            raise FileNotFoundError(input_path)

        if config.end_time <= config.start_time:
            raise ValueError("end time must be after start time")

        video_info = self._get_video_info(input_path)
        if not video_info:
            return

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(config.start_time),
            "-to",
            str(config.end_time),
            "-i",
            input_path,
        ]

        filters = []
        if config.crop_width and config.crop_height:
            crop_x = config.crop_x or 0
            crop_y = config.crop_y or 0
            filters.append(f"crop={config.crop_width}:{config.crop_height}:{crop_x}:{crop_y}")

        if config.output_width and config.output_height:
            filters.append(f"scale={config.output_width}:{config.output_height}")

        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        format_value = getattr(config.format, "value", str(config.format)).lower()
        if format_value == "webm":
            cmd.extend(["-c:v", "libvpx-vp9"])
        elif format_value == "gif":
            cmd.extend(["-vf", "fps=10"])
        else:
            cmd.extend(["-c:v", "libx264"])
            if getattr(config, "quality", None) == "high":
                cmd.extend(["-crf", "18"])

        cmd.append(output_path)

        subprocess.run(cmd, capture_output=True, text=True, check=True)

    def _download_source_video(self, blob_url: str, temp_dir: str) -> str | None:
        """Download source video from blob storage to temp directory."""
        try:
            # Extract blob name from URL
            # URL format: https://{account}.blob.core.windows.net/{container}/{blob_name}
            # Or just blob_name if stored that way

            if blob_url.startswith("http"):
                # Parse URL to get blob name
                from urllib.parse import urlparse

                parsed = urlparse(blob_url)
                path_parts = parsed.path.lstrip("/").split("/", 1)
                if len(path_parts) == 2:
                    blob_name = path_parts[1]
                else:
                    blob_name = path_parts[0]
            else:
                blob_name = blob_url

            if not self.blob_service:
                logger.error("Blob service not configured")
                return None

            # Determine file extension
            ext = Path(blob_name).suffix or ".mp4"
            local_path = os.path.join(temp_dir, f"source{ext}")

            # Download blob
            blob_client = self.blob_service.get_blob_client(
                container=self._container_name,
                blob=blob_name,
            )

            with open(local_path, "wb") as f:
                stream = blob_client.download_blob()
                for chunk in stream.chunks():
                    f.write(chunk)

            logger.info(f"Downloaded source video: {blob_name} -> {local_path}")
            return local_path

        except OSError as e:
            logger.error(f"File error downloading source video: {e}")
            return None
        except Exception as e:
            # Catch Azure SDK exceptions
            logger.error(f"Azure error downloading source video: {e}")
            return None

    def _upload_exported_video(
        self,
        local_path: str,
        clip_id: str,
        platform: str,
    ) -> str | None:
        """Upload exported video to blob storage and return URL."""
        try:
            if not self.blob_service:
                logger.error("Blob service not configured")
                return None

            # Generate blob name
            ext = Path(local_path).suffix
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            blob_name = f"{self._exports_folder}/{clip_id}_{platform}_{timestamp}{ext}"

            # Upload with content type
            blob_client = self.blob_service.get_blob_client(
                container=self._container_name,
                blob=blob_name,
            )

            content_settings = ContentSettings(content_type="video/mp4")

            with open(local_path, "rb") as f:
                blob_client.upload_blob(
                    f,
                    overwrite=True,
                    content_settings=content_settings,
                )

            # Generate URL
            url = blob_client.url
            logger.info(f"Uploaded exported video: {blob_name}")
            return url

        except OSError as e:
            logger.error(f"File error uploading exported video: {e}")
            return None
        except Exception as e:
            # Catch Azure SDK exceptions
            logger.error(f"Azure error uploading exported video: {e}")
            return None

    def _build_ffmpeg_filter(
        self,
        source_width: int,
        source_height: int,
        preset: PlatformPreset,
        crop_mode: CropMode,
        ass_path: str | None = None,
        smart_crop_filter: str | None = None,
    ) -> list[str]:
        """Build FFmpeg filter chain for video processing."""
        filters = []

        # If we have a smart crop filter from face tracking, use it
        if smart_crop_filter and crop_mode == CropMode.FACE_TRACK:
            filters.append(smart_crop_filter)
            # Scale to target resolution after smart crop
            filters.append(f"scale={preset.width}:{preset.height}:flags=lanczos")
        else:
            # Calculate dimensions for aspect ratio conversion
            dims = calculate_target_dimensions(
                source_width=source_width,
                source_height=source_height,
                target_aspect=preset.aspect_ratio,
                target_width=preset.width,
                target_height=preset.height,
                crop_mode=crop_mode,
            )

            # Crop filter (if needed)
            if dims["needs_crop"]:
                filters.append(
                    f"crop={dims['crop_w']}:{dims['crop_h']}:{dims['crop_x']}:{dims['crop_y']}"
                )

            # Scale to target resolution
            filters.append(f"scale={dims['scale_w']}:{dims['scale_h']}:flags=lanczos")

            # Padding for letterbox
            if dims["needs_pad"] and not dims.get("blur_fill"):
                filters.append(
                    f"pad={preset.width}:{preset.height}:{dims['pad_x']}:{dims['pad_y']}:black"
                )

            # Blur fill (complex filter - requires special handling)
            if dims.get("blur_fill"):
                # This needs to be handled differently with split/overlay
                # For now, just use black bars
                filters.append(
                    f"pad={preset.width}:{preset.height}:{dims['pad_x']}:{dims['pad_y']}:black"
                )

        # Subtitles filter (ASS format)
        if ass_path:
            # Escape path for FFmpeg filter
            escaped_path = ass_path.replace("\\", "/").replace(":", "\\:")
            filters.append(f"ass='{escaped_path}'")

        return filters

    def _run_ffmpeg_export(
        self,
        input_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        preset: PlatformPreset,
        quality: QualityPreset,
        crop_mode: CropMode,
        ass_path: str | None = None,
        smart_crop_filter: str | None = None,
        progress_callback: Any = None,
    ) -> bool:
        """Run FFmpeg to export clip with all processing."""
        try:
            # Get source video info
            video_info = self._get_video_info(input_path)
            if not video_info:
                logger.error("Could not get video info")
                return False

            source_width = video_info["width"]
            source_height = video_info["height"]
            duration = end_time - start_time

            # Build filter chain
            filters = self._build_ffmpeg_filter(
                source_width=source_width,
                source_height=source_height,
                preset=preset,
                crop_mode=crop_mode,
                ass_path=ass_path,
                smart_crop_filter=smart_crop_filter,
            )
            filter_str = ",".join(filters) if filters else None

            # Calculate bitrate
            video_bitrate = int(preset.video_bitrate * quality.video_bitrate_multiplier)

            # Build FFmpeg command
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-ss",
                str(start_time),  # Seek to start (fast seek before input)
                "-i",
                input_path,
                "-t",
                str(duration),  # Duration
            ]

            # Add filter chain
            if filter_str:
                cmd.extend(["-vf", filter_str])

            # Video codec settings
            cmd.extend(
                [
                    "-c:v",
                    preset.codec,
                    "-preset",
                    quality.preset,
                    "-crf",
                    str(quality.crf),
                    "-profile:v",
                    preset.profile,
                    "-level:v",
                    preset.level,
                    "-pix_fmt",
                    preset.pixel_format,
                    "-maxrate",
                    f"{video_bitrate}k",
                    "-bufsize",
                    f"{video_bitrate * 2}k",
                ]
            )

            # Audio codec settings
            if video_info.get("has_audio"):
                cmd.extend(
                    [
                        "-c:a",
                        "aac",
                        "-b:a",
                        f"{preset.audio_bitrate}k",
                        "-ar",
                        str(preset.audio_sample_rate),
                    ]
                )
            else:
                cmd.extend(["-an"])  # No audio

            # Fast start for web streaming
            if preset.fast_start:
                cmd.extend(["-movflags", "+faststart"])

            # Output
            cmd.append(output_path)

            logger.info(f"Running FFmpeg: {' '.join(cmd)}")

            # Run FFmpeg
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout, stderr = process.communicate()

            if process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr}")
                return False

            # Verify output exists and has content
            if not os.path.exists(output_path):
                logger.error("Output file was not created")
                return False

            output_size = os.path.getsize(output_path)
            if output_size == 0:
                logger.error("Output file is empty")
                return False

            logger.info(f"Export successful: {output_path} ({output_size / 1024 / 1024:.2f} MB)")
            return True

        except Exception as e:
            logger.error(f"FFmpeg export error: {e}")
            return False

    async def export_clip(
        self,
        clip_id: str,
        platform: ExportPlatform | str = ExportPlatform.TIKTOK,
        quality: ExportQuality | str = ExportQuality.STANDARD,
        crop_mode: CropMode | str | None = None,
        burn_subtitles: bool = True,
    ) -> ExportProgress:
        """
        Export a single clip.

        Args:
            clip_id: ID of the clip to export
            platform: Target platform (tiktok, reels, shorts, youtube, twitter)
            quality: Export quality (draft, standard, high, max)
            crop_mode: Crop mode override (center, letterbox, blur_fill, none)
            burn_subtitles: Whether to burn subtitles into video

        Returns:
            ExportProgress with status and output URL
        """
        progress = ExportProgress(
            clip_id=clip_id,
            status="processing",
            progress_percent=0.0,
            current_step="Initializing",
        )

        temp_dir = None

        try:
            # Get clip
            clip = self.db.get_clip(clip_id)
            if not clip:
                progress.status = "failed"
                progress.error_message = "Clip not found"
                return progress

            # Get project
            project = self.db.get_editor_project(clip.project_id)
            if not project:
                progress.status = "failed"
                progress.error_message = "Project not found"
                return progress

            # Get source media
            media = self.db.get_media(project.source_media_id)
            if not media:
                progress.status = "failed"
                progress.error_message = "Source media not found"
                return progress

            # Get presets
            platform_preset = get_platform_preset(platform)
            quality_preset = get_quality_preset(quality)

            # Use default crop mode if not specified
            if crop_mode is None:
                crop_mode = platform_preset.default_crop_mode
            elif isinstance(crop_mode, str):
                crop_mode = CropMode(crop_mode)

            progress.current_step = "Downloading source video"
            progress.progress_percent = 10.0

            # Create temp directory
            temp_dir = tempfile.mkdtemp(prefix="qprisma_export_")

            # Download source video
            source_path = self._download_source_video(media.blob_url, temp_dir)
            if not source_path:
                progress.status = "failed"
                progress.error_message = "Could not download source video"
                return progress

            progress.current_step = "Preparing subtitles"
            progress.progress_percent = 30.0

            # Generate ASS subtitles if needed
            ass_path = None
            if burn_subtitles and clip.subtitles_enabled and clip.subtitles_data:
                ass_content = self.subtitle_service.generate_ass(
                    subtitle_data=clip.subtitles_data,
                    style=clip.subtitle_style or "hormozi",
                    video_width=platform_preset.width,
                    video_height=platform_preset.height,
                )
                ass_path = os.path.join(temp_dir, "subtitles.ass")
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)

            # Face tracking for smart crop (if requested)
            smart_crop_filter = None
            if crop_mode == CropMode.FACE_TRACK:
                progress.current_step = "Analyzing faces for smart crop"
                progress.progress_percent = 35.0

                try:
                    from services.face_tracking_service import get_face_tracking_service

                    face_service = get_face_tracking_service()
                    smart_crop_result = face_service.analyze_video_for_smart_crop(
                        video_path=source_path,
                        start_time=clip.start_time,
                        end_time=clip.end_time,
                        target_aspect_ratio=9 / 16,  # Vertical
                        sample_interval=0.5,  # Analyze every 0.5 seconds
                    )

                    if smart_crop_result.keyframes:
                        smart_crop_filter = face_service.generate_ffmpeg_crop_filter(
                            smart_crop_result,
                            use_keyframes=True,
                        )
                        logger.info(
                            f"Face tracking: analyzed {smart_crop_result.frames_analyzed} frames, "
                            f"detected {smart_crop_result.faces_detected} faces"
                        )
                except Exception as e:
                    logger.warning(f"Face tracking failed, falling back to center crop: {e}")
                    crop_mode = CropMode.CENTER

            progress.current_step = "Encoding video"
            progress.progress_percent = 40.0

            # Output path
            output_path = os.path.join(temp_dir, f"export_{platform_preset.name}.mp4")

            # Run FFmpeg export
            success = self._run_ffmpeg_export(
                input_path=source_path,
                output_path=output_path,
                start_time=clip.start_time,
                end_time=clip.end_time,
                preset=platform_preset,
                quality=quality_preset,
                crop_mode=crop_mode,
                ass_path=ass_path,
                smart_crop_filter=smart_crop_filter,
            )

            if not success:
                progress.status = "failed"
                progress.error_message = "FFmpeg encoding failed"
                return progress

            progress.current_step = "Uploading to storage"
            progress.progress_percent = 80.0

            # Upload to blob storage
            output_url = self._upload_exported_video(
                local_path=output_path,
                clip_id=clip_id,
                platform=platform_preset.name,
            )

            if not output_url:
                progress.status = "failed"
                progress.error_message = "Could not upload exported video"
                return progress

            # Update clip in database
            self.db.update_clip(
                clip_id,
                {
                    "export_status": "done",
                    "export_url": output_url,
                    "export_format": platform_preset.name,
                },
            )

            # Get file size
            file_size = os.path.getsize(output_path)

            progress.status = "done"
            progress.progress_percent = 100.0
            progress.current_step = "Complete"
            progress.output_url = output_url
            progress.file_size_bytes = file_size
            progress.duration_seconds = clip.end_time - clip.start_time

            return progress

        except Exception as e:
            logger.error(f"Export error: {e}")
            progress.status = "failed"
            progress.error_message = str(e)
            return progress

        finally:
            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Could not cleanup temp dir: {e}")

    async def export_clips_batch(
        self,
        project_id: str,
        clip_ids: list[str] | None = None,
        platform: ExportPlatform | str = ExportPlatform.TIKTOK,
        quality: ExportQuality | str = ExportQuality.STANDARD,
        crop_mode: CropMode | str | None = None,
        burn_subtitles: bool = True,
    ) -> list[ExportProgress]:
        """
        Export multiple clips from a project.

        Args:
            project_id: ID of the project
            clip_ids: Specific clip IDs to export (None = all clips)
            platform: Target platform
            quality: Export quality
            crop_mode: Crop mode override
            burn_subtitles: Whether to burn subtitles

        Returns:
            List of ExportProgress for each clip
        """
        # Get clips to export
        if clip_ids:
            clips = [self.db.get_clip(cid) for cid in clip_ids]
            clips = [c for c in clips if c is not None]
        else:
            clips = self.db.list_clips(project_id)

        if not clips:
            return []

        results = []

        for clip in clips:
            # Mark as processing
            self.db.update_clip(clip.id, {"export_status": "processing"})

            # Export clip
            progress = await self.export_clip(
                clip_id=clip.id,
                platform=platform,
                quality=quality,
                crop_mode=crop_mode,
                burn_subtitles=burn_subtitles,
            )

            results.append(progress)

        return results

    def get_available_presets(self) -> dict[str, Any]:
        """Get all available export presets."""
        return {
            "platforms": {
                name: {
                    "name": preset.name,
                    "display_name": preset.display_name,
                    "aspect_ratio": preset.aspect_ratio.value,
                    "resolution": f"{preset.width}x{preset.height}",
                    "max_duration": preset.max_duration,
                    "max_file_size_mb": preset.max_file_size_mb,
                }
                for name, preset in PLATFORM_PRESETS.items()
            },
            "qualities": {
                name: {
                    "name": preset.name,
                    "crf": preset.crf,
                    "preset": preset.preset,
                    "description": self._get_quality_description(name),
                }
                for name, preset in QUALITY_PRESETS.items()
            },
            "crop_modes": [
                {"id": "none", "name": "None", "description": "Keep original aspect ratio"},
                {"id": "center", "name": "Center Crop", "description": "Crop to center of frame"},
                {"id": "letterbox", "name": "Letterbox", "description": "Add black bars to fit"},
                {
                    "id": "blur_fill",
                    "name": "Blur Fill",
                    "description": "Fill with blurred background",
                },
            ],
        }

    def _get_quality_description(self, quality: str) -> str:
        """Get human-readable description for quality preset."""
        descriptions = {
            "draft": "Fast encoding, lower quality. Good for previews.",
            "standard": "Balanced speed and quality. Recommended for most exports.",
            "high": "Higher quality, slower encoding. Good for final exports.",
            "max": "Maximum quality, slowest encoding. Professional use.",
        }
        return descriptions.get(quality, "")

    def estimate_export_time(
        self,
        duration_seconds: float,
        platform: str,
        quality: str,
    ) -> dict[str, Any]:
        """Estimate export time and file size."""
        preset = get_platform_preset(platform)
        quality_preset = get_quality_preset(quality)

        # Rough estimates based on quality preset
        time_multipliers = {
            "draft": 0.3,  # ~3x faster than realtime
            "standard": 1.0,  # ~1x realtime
            "high": 2.5,  # ~0.4x realtime
            "max": 5.0,  # ~0.2x realtime
        }

        # Estimated bitrate in kbps
        estimated_bitrate = preset.video_bitrate * quality_preset.video_bitrate_multiplier
        estimated_bitrate += preset.audio_bitrate

        # File size estimate (bitrate * duration / 8 for bytes)
        estimated_size_mb = (estimated_bitrate * duration_seconds) / 8 / 1024

        # Time estimate
        time_multiplier = time_multipliers.get(quality, 1.0)
        estimated_time = duration_seconds * time_multiplier

        return {
            "estimated_time_seconds": estimated_time,
            "estimated_size_mb": round(estimated_size_mb, 2),
            "estimated_bitrate_kbps": round(estimated_bitrate),
            "output_resolution": f"{preset.width}x{preset.height}",
        }


# Singleton instance
_export_service: ExportService | None = None


def get_export_service() -> ExportService:
    """Get or create the export service singleton."""
    global _export_service
    if _export_service is None:
        _export_service = ExportService()
    return _export_service
