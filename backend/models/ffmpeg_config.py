"""
FFmpeg Configuration Models
Pydantic models for video processing configuration with FFmpeg.
Inspired by the Edconv architecture for maximum customization.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LogLevel(str, Enum):
    """FFmpeg log levels"""

    QUIET = "quiet"
    PANIC = "panic"
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    VERBOSE = "verbose"
    DEBUG = "debug"
    TRACE = "trace"


class PixelFormat(str, Enum):
    """Supported pixel formats"""

    YUV420P = "yuv420p"  # 8-bit
    YUV420P10LE = "yuv420p10le"  # 10-bit
    YUV422P = "yuv422p"
    YUV444P = "yuv444p"
    RGB24 = "rgb24"
    RGBA = "rgba"
    GRAY = "gray"


class VideoCodec(str, Enum):
    """Supported video codecs"""

    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    AV1 = "libsvtav1"
    COPY = "copy"


class ScalingFilter(str, Enum):
    """Scaling filters"""

    BILINEAR = "bilinear"
    BICUBIC = "bicubic"
    LANCZOS = "lanczos"
    SPLINE16 = "spline16"
    SPLINE36 = "spline36"
    NEIGHBOR = "neighbor"


class FrameExtractionMethod(str, Enum):
    """Frame extraction methods"""

    FPS = "fps"  # Extract at N FPS
    INTERVAL = "interval"  # Extract every N seconds
    KEYFRAMES = "keyframes"  # Keyframes only
    SCENE_DETECT = "scene_detect"  # Scene change detection
    UNIFORM = "uniform"  # N frames uniformly distributed
    ADAPTIVE = "adaptive"  # Adaptive based on video duration
    HYBRID = "hybrid"  # Combination of scene_detect + uniform fill


class FrameExtractionConfig(BaseModel):
    """Frame extraction configuration"""

    method: FrameExtractionMethod = Field(
        default=FrameExtractionMethod.FPS, description="Frame extraction method"
    )

    # For FPS method
    fps: float | None = Field(
        default=1.0, description="Frames per second to extract (FPS method)", gt=0, le=60
    )

    # For INTERVAL method
    interval_seconds: float | None = Field(
        default=5.0, description="Interval in seconds between frames (INTERVAL method)", gt=0
    )

    # For UNIFORM method
    num_frames: int | None = Field(
        default=10, description="Total number of frames to extract (UNIFORM method)", gt=0, le=1000
    )

    # For SCENE_DETECT method
    scene_threshold: float | None = Field(
        default=0.4, description="Scene detection threshold (0-1)", ge=0, le=1
    )

    # For HYBRID method (scene_detect + uniform fill)
    hybrid_scene_ratio: float | None = Field(
        default=0.6,
        description="Ratio of scene frames vs uniform fill (0.6 = 60% scenes, 40% fill)",
        ge=0,
        le=1,
    )
    hybrid_min_gap_seconds: float | None = Field(
        default=10.0,
        description="Minimum gap in seconds between frames before inserting fill frames",
        gt=0,
    )

    # Decoder backend
    decoder_backend: str = Field(
        default="pyav",
        description="Decoder backend: 'pyav' (in-process) or 'ffmpeg_subprocess'",
    )

    # Frame deduplication (perceptual hashing)
    deduplication_enabled: bool = Field(
        default=True,
        description="Remove near-duplicate frames using perceptual hashing",
    )
    deduplication_threshold: int = Field(
        default=5,
        description="Hamming distance threshold for phash dedup (lower = stricter)",
        ge=0,
        le=64,
    )

    # General limits
    max_frames: int | None = Field(
        default=100, description="Maximum number of frames to extract", gt=0
    )

    start_time: float | None = Field(
        default=None, description="Start time in seconds (None = from the beginning)", ge=0
    )

    end_time: float | None = Field(
        default=None, description="End time in seconds (None = until the end)", gt=0
    )

    @field_validator("end_time")
    @classmethod
    def end_time_must_be_after_start(cls, v: float | None, info) -> float | None:
        """Validate that end_time > start_time"""
        if (
            v is not None
            and info.data.get("start_time") is not None
            and v <= info.data["start_time"]
        ):
            raise ValueError("end_time must be greater than start_time")
        return v


class VideoFilterConfig(BaseModel):
    """Video filter configuration"""

    # Scaling
    scale_width: int | None = Field(
        default=None, description="Scale width (None = keep original)", gt=0
    )
    scale_height: int | None = Field(
        default=None, description="Scale height (None = keep original)", gt=0
    )
    scaling_filter: ScalingFilter = Field(
        default=ScalingFilter.LANCZOS, description="Scaling algorithm"
    )

    # Pixel format
    pixel_format: PixelFormat | None = Field(default=None, description="Output pixel format")

    # Crop
    crop_x: int | None = Field(default=None, description="Crop X position", ge=0)
    crop_y: int | None = Field(default=None, description="Crop Y position", ge=0)
    crop_width: int | None = Field(default=None, description="Crop width", gt=0)
    crop_height: int | None = Field(default=None, description="Crop height", gt=0)

    # Color adjustments
    brightness: float | None = Field(
        default=None, description="Brightness adjustment (-1 to 1)", ge=-1, le=1
    )
    contrast: float | None = Field(
        default=None, description="Contrast adjustment (0 to 4)", ge=0, le=4
    )
    saturation: float | None = Field(
        default=None, description="Saturation adjustment (0 to 3)", ge=0, le=3
    )

    # Rotation
    rotate: int | None = Field(default=None, description="Rotation in degrees (0, 90, 180, 270)")

    # Deinterlacing
    deinterlace: bool = Field(default=False, description="Apply deinterlacing")

    # HDR to SDR
    hdr_to_sdr: bool = Field(default=False, description="Convert HDR to SDR")

    # Custom filters
    custom_filters: list[str] | None = Field(
        default=None, description="Additional custom FFmpeg filters"
    )

    @field_validator("rotate")
    @classmethod
    def validate_rotation(cls, v: int | None) -> int | None:
        """Validate rotation"""
        if v is not None and v not in [0, 90, 180, 270]:
            raise ValueError("rotate must be 0, 90, 180, or 270")
        return v


class QualityPreset(str, Enum):
    """Quality presets"""

    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class VideoEncodingConfig(BaseModel):
    """Video encoding configuration"""

    codec: VideoCodec = Field(default=VideoCodec.H264, description="Video codec")

    preset: QualityPreset = Field(default=QualityPreset.MEDIUM, description="Speed/quality preset")

    crf: int | None = Field(
        default=23, description="Constant Rate Factor (quality, lower = better)", ge=0, le=51
    )

    bitrate: str | None = Field(default=None, description="Target bitrate (e.g.: '5M', '1000k')")

    max_bitrate: str | None = Field(default=None, description="Maximum bitrate")

    buffer_size: str | None = Field(default=None, description="Buffer size")

    gop_size: int | None = Field(default=None, description="GOP size (Group of Pictures)", gt=0)

    profile: str | None = Field(default=None, description="Codec profile (e.g.: 'high', 'main')")

    level: str | None = Field(default=None, description="Codec level (e.g.: '4.0', '5.1')")


class FFmpegProcessingConfig(BaseModel):
    """Complete FFmpeg processing configuration"""

    # Frame extraction
    frame_extraction: FrameExtractionConfig = Field(
        default_factory=FrameExtractionConfig, description="Frame extraction configuration"
    )

    # Video filters
    video_filters: VideoFilterConfig = Field(
        default_factory=VideoFilterConfig, description="Video filter configuration"
    )

    # Encoding (optional, for generating clips)
    encoding: VideoEncodingConfig | None = Field(
        default=None, description="Encoding configuration (if output videos are generated)"
    )

    # General FFmpeg configuration
    log_level: LogLevel = Field(default=LogLevel.ERROR, description="FFmpeg logging level")

    threads: int | None = Field(
        default=None, description="Number of threads (None = auto)", gt=0, le=32
    )

    hardware_accel: str | None = Field(
        default=None,
        description="Hardware acceleration: 'auto' (detect), 'cuda', 'qsv', 'vaapi', 'videotoolbox', or None (CPU only)",
    )

    # Advanced options
    custom_input_args: dict[str, Any] | None = Field(
        default=None, description="Custom input arguments"
    )

    custom_output_args: dict[str, Any] | None = Field(
        default=None, description="Custom output arguments"
    )

    # Metadata
    metadata: dict[str, str] | None = Field(
        default=None, description="Metadata to include in the output"
    )

    model_config = {"use_enum_values": True}


class ProcessingPreset(str, Enum):
    """Predefined processing presets"""

    FAST_PREVIEW = "fast_preview"  # Fast extraction, low quality
    BALANCED = "balanced"  # Speed/quality balance
    HIGH_QUALITY = "high_quality"  # Maximum quality
    KEYFRAMES_ONLY = "keyframes_only"  # Keyframes only
    SCENE_ANALYSIS = "scene_analysis"  # Scene analysis
    TIMELINE_PREVIEW = "timeline_preview"  # Timeline preview
    # New presets
    DEEP_ANALYSIS = "deep_analysis"  # Long videos, maximum coverage
    ULTRA_DEEP = "ultra_deep"  # Very long videos (4+ hours), maximum extraction
    INTERVIEW_MODE = "interview_mode"  # Prioritizes audio, fewer visual frames
    ACTION_MODE = "action_mode"  # More frames in scenes with motion
    ADAPTIVE = "adaptive"  # Automatic adjustment based on duration


def get_adaptive_config(duration_seconds: float) -> FrameExtractionConfig:
    """
    Calculates optimal extraction configuration based on video duration.

    Args:
        duration_seconds: Video duration in seconds

    Returns:
        FrameExtractionConfig optimized for the duration
    """
    duration_minutes = duration_seconds / 60

    if duration_minutes < 5:
        # Very short videos: maximum density with scene detection
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=1.0,
            scene_threshold=0.35,
            hybrid_scene_ratio=0.6,
            hybrid_min_gap_seconds=3.0,
            max_frames=300,
        )
    elif duration_minutes < 30:
        # Short to medium videos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.INTERVAL,
            interval_seconds=3.0,
            max_frames=400,
        )
    elif duration_minutes < 60:
        # ~1 hour videos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=4.0,
            scene_threshold=0.35,
            hybrid_scene_ratio=0.6,
            hybrid_min_gap_seconds=15.0,
            max_frames=600,
        )
    elif duration_minutes < 120:
        # 1-2 hour videos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=5.0,
            scene_threshold=0.3,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=20.0,
            max_frames=800,
        )
    elif duration_minutes < 240:
        # 2-4 hour videos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=6.0,
            scene_threshold=0.25,
            hybrid_scene_ratio=0.4,
            hybrid_min_gap_seconds=30.0,
            max_frames=1200,
        )
    elif duration_minutes < 480:
        # 4-8 hour videos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=8.0,
            scene_threshold=0.2,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=45.0,
            max_frames=1500,
        )
    else:
        # Very long videos (>8 hours)
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=10.0,
            scene_threshold=0.15,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=60.0,
            max_frames=2000,
        )


def get_preset_config(preset: ProcessingPreset) -> FFmpegProcessingConfig:
    """
    Get predefined configuration based on preset

    Args:
        preset: Preset to use

    Returns:
        FFmpeg configuration
    """
    if preset == ProcessingPreset.FAST_PREVIEW:
        # Increased from 20 to 50 frames for better coverage
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=10.0, max_frames=50
            ),
            video_filters=VideoFilterConfig(
                scale_width=640, scale_height=360, pixel_format=PixelFormat.YUV420P
            ),
        )

    elif preset == ProcessingPreset.BALANCED:
        # Increased from 100 to 200 frames, with adaptive interval
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=5.0, max_frames=200
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
        )

    elif preset == ProcessingPreset.HIGH_QUALITY:
        # Increased from 500 to 600 frames for comprehensive coverage
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=3.0, max_frames=600
            ),
            video_filters=VideoFilterConfig(
                scaling_filter=ScalingFilter.LANCZOS, pixel_format=PixelFormat.YUV420P
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.KEYFRAMES_ONLY:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.KEYFRAMES, max_frames=200
            )
        )

    elif preset == ProcessingPreset.SCENE_ANALYSIS:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.SCENE_DETECT, scene_threshold=0.4, max_frames=150
            ),
            video_filters=VideoFilterConfig(scale_width=1280, scale_height=720),
        )

    elif preset == ProcessingPreset.TIMELINE_PREVIEW:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.UNIFORM, num_frames=30
            ),
            video_filters=VideoFilterConfig(scale_width=320, scale_height=180),
        )

    elif preset == ProcessingPreset.DEEP_ANALYSIS:
        # For long videos - maximum coverage with hybrid mode
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.3,
                hybrid_scene_ratio=0.5,
                hybrid_min_gap_seconds=20.0,
                max_frames=1000,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.ULTRA_DEEP:
        # For very long videos (4+ hours) - maximum extraction
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.2,
                hybrid_scene_ratio=0.5,
                hybrid_min_gap_seconds=30.0,
                max_frames=2000,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.INTERVIEW_MODE:
        # Prioritizes audio - fewer visual frames, longer intervals
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL,
                interval_seconds=10.0,
                max_frames=200,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280,
                scale_height=720,
            ),
        )

    elif preset == ProcessingPreset.ACTION_MODE:
        # More frames, aggressive scene detection to capture motion
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.2,  # More sensitive to changes
                hybrid_scene_ratio=0.7,  # More weight on scene detection
                hybrid_min_gap_seconds=5.0,  # Less tolerance for gaps
                max_frames=800,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1920, scale_height=1080, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.ADAPTIVE:
        # Placeholder - configured dynamically based on duration
        # Use get_adaptive_config(duration) to obtain the real config
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.ADAPTIVE,
                max_frames=500,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
        )

    else:
        return FFmpegProcessingConfig()


class ProcessingStatus(BaseModel):
    """Processing status"""

    status: str = Field(description="Current status (pending, processing, completed, failed)")
    progress: float = Field(default=0.0, description="Progress 0-100", ge=0, le=100)
    current_frame: int = Field(default=0, description="Current frame being processed")
    total_frames: int = Field(default=0, description="Total frames to process")
    fps: float | None = Field(default=None, description="Processing FPS")
    eta_seconds: float | None = Field(
        default=None, description="Estimated remaining time in seconds"
    )
    error: str | None = Field(default=None, description="Error message if status=failed")

    # Source video information
    video_duration: float | None = Field(default=None, description="Video duration in seconds")
    video_fps: float | None = Field(default=None, description="Source video FPS")
    video_width: int | None = Field(default=None, description="Video width")
    video_height: int | None = Field(default=None, description="Video height")

    # Results
    frames_extracted: int = Field(default=0, description="Successfully extracted frames")
    frames_analyzed: int = Field(default=0, description="Frames analyzed with GPT-Vision")
    storage_used_mb: float | None = Field(default=None, description="Storage used in MB")


class ProcessingPipeline(BaseModel):
    """Processing pipeline representation for the graph"""

    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Graph nodes (pipeline steps)"
    )
    edges: list[dict[str, Any]] = Field(
        default_factory=list, description="Connections between nodes"
    )
    config: FFmpegProcessingConfig = Field(description="Applied configuration")
