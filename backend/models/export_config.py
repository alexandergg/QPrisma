"""
Export configuration models and platform presets for video export.

This module defines:
- Export presets for each platform (TikTok, Reels, Shorts, YouTube, Twitter)
- Quality presets (draft, standard, high, max)
- Export request/response models
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    """Legacy export formats used by tests."""

    MP4 = "mp4"
    WEBM = "webm"
    GIF = "gif"


class ExportConfig(BaseModel):
    """Legacy export configuration used by tests."""

    start_time: float
    end_time: float
    format: ExportFormat
    quality: str = "standard"
    crop_x: int | None = None
    crop_y: int | None = None
    crop_width: int | None = None
    crop_height: int | None = None
    output_width: int | None = None
    output_height: int | None = None


class ExportPlatform(str, Enum):
    """Supported export platforms."""

    TIKTOK = "tiktok"
    REELS = "reels"
    SHORTS = "shorts"
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    CUSTOM = "custom"


class ExportQuality(str, Enum):
    """Export quality presets."""

    DRAFT = "draft"  # Fast encoding, lower quality (for preview)
    STANDARD = "standard"  # Balanced speed/quality
    HIGH = "high"  # Higher quality, slower encoding
    MAX = "max"  # Maximum quality, slowest


class AspectRatio(str, Enum):
    """Supported aspect ratios."""

    VERTICAL = "9:16"  # TikTok, Reels, Shorts
    HORIZONTAL = "16:9"  # YouTube, Twitter
    SQUARE = "1:1"  # Instagram posts


class CropMode(str, Enum):
    """How to handle aspect ratio conversion."""

    NONE = "none"  # No cropping, use original
    CENTER = "center"  # Center crop
    FACE_TRACK = "face_track"  # Follow faces (smart crop)
    LETTERBOX = "letterbox"  # Add black bars
    BLUR_FILL = "blur_fill"  # Blurred background fill


class PlatformPreset(BaseModel):
    """Platform-specific export configuration."""

    name: str
    display_name: str
    aspect_ratio: AspectRatio
    width: int
    height: int
    max_duration: int | None = None  # seconds, None = unlimited
    max_file_size_mb: int | None = None

    # Video codec settings
    codec: str = "libx264"
    profile: str = "high"
    level: str = "4.2"
    pixel_format: str = "yuv420p"

    # Bitrate settings (kbps)
    video_bitrate: int = 8000
    audio_bitrate: int = 192
    audio_sample_rate: int = 44100

    # Default crop mode for this platform
    default_crop_mode: CropMode = CropMode.CENTER

    # Platform-specific flags
    optimize_for_web: bool = True
    fast_start: bool = True  # moov atom at beginning for streaming


class QualityPreset(BaseModel):
    """Quality-specific encoding settings."""

    name: str
    crf: int  # Constant Rate Factor (lower = better quality)
    preset: str  # FFmpeg encoding preset
    two_pass: bool = False
    video_bitrate_multiplier: float = 1.0


# Platform presets
PLATFORM_PRESETS: dict[str, PlatformPreset] = {
    "tiktok": PlatformPreset(
        name="tiktok",
        display_name="TikTok",
        aspect_ratio=AspectRatio.VERTICAL,
        width=1080,
        height=1920,
        max_duration=180,  # 3 minutes
        max_file_size_mb=287,
        codec="libx264",
        profile="high",
        video_bitrate=8000,
        audio_bitrate=192,
        default_crop_mode=CropMode.CENTER,
    ),
    "reels": PlatformPreset(
        name="reels",
        display_name="Instagram Reels",
        aspect_ratio=AspectRatio.VERTICAL,
        width=1080,
        height=1920,
        max_duration=90,  # 90 seconds
        max_file_size_mb=250,
        codec="libx264",
        profile="high",
        video_bitrate=8000,
        audio_bitrate=192,
        default_crop_mode=CropMode.CENTER,
    ),
    "shorts": PlatformPreset(
        name="shorts",
        display_name="YouTube Shorts",
        aspect_ratio=AspectRatio.VERTICAL,
        width=1080,
        height=1920,
        max_duration=60,  # 60 seconds
        max_file_size_mb=None,  # YouTube handles large files
        codec="libx264",
        profile="high",
        video_bitrate=10000,  # YouTube likes higher bitrate
        audio_bitrate=192,
        default_crop_mode=CropMode.CENTER,
    ),
    "youtube": PlatformPreset(
        name="youtube",
        display_name="YouTube",
        aspect_ratio=AspectRatio.HORIZONTAL,
        width=1920,
        height=1080,
        max_duration=None,  # Unlimited for verified accounts
        max_file_size_mb=None,
        codec="libx264",
        profile="high",
        level="4.2",
        video_bitrate=12000,
        audio_bitrate=320,
        audio_sample_rate=48000,
        default_crop_mode=CropMode.NONE,
    ),
    "twitter": PlatformPreset(
        name="twitter",
        display_name="X (Twitter)",
        aspect_ratio=AspectRatio.HORIZONTAL,
        width=1280,
        height=720,
        max_duration=140,  # 2:20
        max_file_size_mb=512,
        codec="libx264",
        profile="high",
        video_bitrate=5000,
        audio_bitrate=128,
        default_crop_mode=CropMode.NONE,
    ),
}

# Quality presets
QUALITY_PRESETS: dict[str, QualityPreset] = {
    "draft": QualityPreset(
        name="draft",
        crf=28,
        preset="ultrafast",
        two_pass=False,
        video_bitrate_multiplier=0.6,
    ),
    "standard": QualityPreset(
        name="standard",
        crf=23,
        preset="medium",
        two_pass=False,
        video_bitrate_multiplier=1.0,
    ),
    "high": QualityPreset(
        name="high",
        crf=20,
        preset="slow",
        two_pass=False,
        video_bitrate_multiplier=1.3,
    ),
    "max": QualityPreset(
        name="max",
        crf=18,
        preset="veryslow",
        two_pass=True,
        video_bitrate_multiplier=1.5,
    ),
}


class ExportRequest(BaseModel):
    """Request to export a clip."""

    clip_id: str
    platform: ExportPlatform = ExportPlatform.TIKTOK
    quality: ExportQuality = ExportQuality.STANDARD

    # Override defaults
    crop_mode: CropMode | None = None
    burn_subtitles: bool = True

    # Optional custom settings
    custom_width: int | None = None
    custom_height: int | None = None
    custom_bitrate: int | None = None


class BatchExportRequest(BaseModel):
    """Request to export multiple clips."""

    clip_ids: list[str] = Field(
        default_factory=list, description="Specific clips to export, empty = all clips"
    )
    platform: ExportPlatform = ExportPlatform.TIKTOK
    quality: ExportQuality = ExportQuality.STANDARD
    crop_mode: CropMode | None = None
    burn_subtitles: bool = True


class ExportProgress(BaseModel):
    """Progress information for an export job."""

    clip_id: str
    status: Literal["queued", "processing", "encoding", "uploading", "done", "failed"]
    progress_percent: float = 0.0
    current_step: str = ""
    error_message: str | None = None
    output_url: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: float | None = None


class ExportJobResponse(BaseModel):
    """Response for an export job."""

    job_id: str
    project_id: str
    clips: list[ExportProgress]
    total_clips: int
    completed_clips: int
    failed_clips: int
    status: Literal["pending", "processing", "completed", "failed", "cancelled"]
    created_at: str
    updated_at: str | None = None
    download_url: str | None = None  # ZIP for batch exports


def get_platform_preset(platform: str | ExportPlatform) -> PlatformPreset:
    """Get platform preset by name."""
    if isinstance(platform, ExportPlatform):
        platform = platform.value

    if platform not in PLATFORM_PRESETS:
        raise ValueError(
            f"Unknown platform: {platform}. Available: {list(PLATFORM_PRESETS.keys())}"
        )

    return PLATFORM_PRESETS[platform]


def get_quality_preset(quality: str | ExportQuality) -> QualityPreset:
    """Get quality preset by name."""
    if isinstance(quality, ExportQuality):
        quality = quality.value

    if quality not in QUALITY_PRESETS:
        raise ValueError(f"Unknown quality: {quality}. Available: {list(QUALITY_PRESETS.keys())}")

    return QUALITY_PRESETS[quality]


def calculate_target_dimensions(
    source_width: int,
    source_height: int,
    target_aspect: AspectRatio,
    target_width: int,
    target_height: int,
    crop_mode: CropMode,
) -> dict:
    """
    Calculate crop and scale parameters for aspect ratio conversion.

    Returns dict with:
    - crop_x, crop_y, crop_w, crop_h: Crop region from source
    - scale_w, scale_h: Final output dimensions
    - pad_x, pad_y, pad_w, pad_h: Padding for letterbox mode
    """
    source_aspect = source_width / source_height
    target_aspect_val = target_width / target_height

    result = {
        "crop_x": 0,
        "crop_y": 0,
        "crop_w": source_width,
        "crop_h": source_height,
        "scale_w": target_width,
        "scale_h": target_height,
        "pad_x": 0,
        "pad_y": 0,
        "pad_w": target_width,
        "pad_h": target_height,
        "needs_crop": False,
        "needs_pad": False,
    }

    if crop_mode == CropMode.NONE:
        # Just scale to fit, maintaining aspect ratio
        if source_aspect > target_aspect_val:
            # Source is wider - fit to width
            result["scale_w"] = target_width
            result["scale_h"] = int(target_width / source_aspect)
        else:
            # Source is taller - fit to height
            result["scale_h"] = target_height
            result["scale_w"] = int(target_height * source_aspect)
        return result

    if crop_mode == CropMode.LETTERBOX:
        result["needs_pad"] = True
        if source_aspect > target_aspect_val:
            # Source is wider - add top/bottom bars
            scaled_height = int(target_width / source_aspect)
            result["scale_w"] = target_width
            result["scale_h"] = scaled_height
            result["pad_y"] = (target_height - scaled_height) // 2
        else:
            # Source is taller - add side bars
            scaled_width = int(target_height * source_aspect)
            result["scale_w"] = scaled_width
            result["scale_h"] = target_height
            result["pad_x"] = (target_width - scaled_width) // 2
        return result

    if crop_mode in (CropMode.CENTER, CropMode.FACE_TRACK):
        result["needs_crop"] = True

        if source_aspect > target_aspect_val:
            # Source is wider than target - crop sides
            new_width = int(source_height * target_aspect_val)
            result["crop_x"] = (source_width - new_width) // 2
            result["crop_w"] = new_width
        else:
            # Source is taller than target - crop top/bottom
            new_height = int(source_width / target_aspect_val)
            result["crop_y"] = (source_height - new_height) // 2
            result["crop_h"] = new_height

        return result

    if crop_mode == CropMode.BLUR_FILL:
        # This requires special handling in FFmpeg (overlay blurred background)
        result["needs_pad"] = True
        result["blur_fill"] = True
        if source_aspect > target_aspect_val:
            scaled_height = int(target_width / source_aspect)
            result["scale_w"] = target_width
            result["scale_h"] = scaled_height
            result["pad_y"] = (target_height - scaled_height) // 2
        else:
            scaled_width = int(target_height * source_aspect)
            result["scale_w"] = scaled_width
            result["scale_h"] = target_height
            result["pad_x"] = (target_width - scaled_width) // 2
        return result

    return result
