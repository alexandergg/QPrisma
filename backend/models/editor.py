"""
Pydantic models for the Video Editor API.

These models handle request/response validation for:
- Editor Projects
- Clips
- Subtitles
- Export operations
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class ProjectStatus(str, Enum):
    """Status of an editor project."""

    DRAFT = "draft"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ExportFormat(str, Enum):
    """Target platform for export."""

    TIKTOK = "tiktok"
    REELS = "reels"
    SHORTS = "shorts"
    YOUTUBE = "youtube"
    TWITTER = "twitter"


class SubtitleStyle(str, Enum):
    """Pre-defined subtitle styles."""

    HORMOZI = "hormozi"  # Word by word, bold, alternating colors
    MRBEAST = "mrbeast"  # Large, centered, dramatic shadow
    MINIMAL = "minimal"  # Small, no background
    KARAOKE = "karaoke"  # Highlight current word
    NEWS = "news"  # Lower third, solid background


class ClipExportStatus(str, Enum):
    """Export status for individual clips."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# =============================================================================
# Project Models
# =============================================================================


class ProjectSettings(BaseModel):
    """Settings for an editor project."""

    target_aspect_ratio: str = Field(default="16:9", description="Target aspect ratio")
    target_resolution: str = Field(default="1920x1080", description="Target resolution")
    default_subtitle_style: SubtitleStyle | None = None


class ProjectCreate(BaseModel):
    """Request model for creating a new project."""

    source_media_id: str = Field(..., description="ID of the source video")
    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: str | None = Field(default=None, description="Project description")
    settings: ProjectSettings | None = Field(default=None, description="Project settings")

    class Config:
        json_schema_extra = {
            "example": {
                "source_media_id": "media_abc123",
                "name": "My Podcast Ep.42 Clips",
                "description": "Viral clips from episode 42",
                "settings": {"target_aspect_ratio": "9:16", "target_resolution": "1080x1920"},
            }
        }


class ProjectUpdate(BaseModel):
    """Request model for updating a project."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: ProjectStatus | None = None
    settings: ProjectSettings | None = None


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    user_id: str
    source_media_id: str
    name: str
    description: str | None
    status: ProjectStatus
    settings: dict | None
    export_format: str | None
    export_url: str | None
    created_at: datetime
    updated_at: datetime
    clips_count: int = 0

    class Config:
        from_attributes = True


class SourceMediaInfo(BaseModel):
    """Information about the source media for a project."""

    id: str
    filename: str | None
    duration: float | None
    blob_url: str | None
    media_type: str | None
    processed: bool | None = None


class ProjectWithClips(ProjectResponse):
    """Response model for a project with its clips and source media."""

    clips: list["ClipResponse"] = []
    source_media: SourceMediaInfo | None = None


# =============================================================================
# Clip Models
# =============================================================================


class ClipCreate(BaseModel):
    """Request model for creating a clip."""

    start_time: float = Field(..., ge=0, description="Start time in seconds")
    end_time: float = Field(..., gt=0, description="End time in seconds")
    title: str | None = Field(default=None, max_length=255, description="Clip title")
    notes: str | None = Field(default=None, description="Notes about the clip")
    order: int | None = Field(default=None, ge=0, description="Position in timeline")

    # AI metadata (optional, set by system)
    is_ai_suggested: bool = False
    viral_score: float | None = Field(default=None, ge=0, le=100)
    viral_reasons: list[str] | None = None
    transcript_snippet: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "start_time": 734.5,
                "end_time": 764.5,
                "title": "Introduction to AI",
                "notes": "Good hook at the start",
            }
        }


class ClipUpdate(BaseModel):
    """Request model for updating a clip."""

    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    order: int | None = Field(default=None, ge=0)


class ClipReorder(BaseModel):
    """Request model for reordering clips."""

    clip_ids: list[str] = Field(..., description="Ordered list of clip IDs")


class SubtitleSettings(BaseModel):
    """Settings for subtitle styling."""

    font_family: str = Field(default="Inter", description="Font family")
    font_size: str = Field(default="M", description="Size: S, M, L, XL")
    text_color: str = Field(default="#FFFFFF", description="Text color hex")
    highlight_color: str | None = Field(default="#FFD700", description="Highlight color hex")
    background_color: str | None = Field(default=None, description="Background color hex")
    position: str = Field(default="bottom-center", description="Position on screen")
    animation: str = Field(default="fade", description="Animation type")


class ClipSubtitleUpdate(BaseModel):
    """Request model for updating clip subtitles."""

    subtitles_enabled: bool = True
    subtitle_style: SubtitleStyle = SubtitleStyle.HORMOZI
    subtitle_settings: SubtitleSettings | None = None


class ClipResponse(BaseModel):
    """Response model for a clip."""

    id: str
    project_id: str
    start_time: float
    end_time: float
    duration: float
    order: int
    title: str | None
    notes: str | None
    is_ai_suggested: bool
    viral_score: float | None
    viral_reasons: list[str] | None
    transcript_snippet: str | None
    subtitle_style: str | None
    subtitles_enabled: bool
    subtitles_data: dict | None
    subtitle_settings: dict | None
    export_status: ClipExportStatus
    export_url: str | None
    export_format: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Export Models
# =============================================================================


class ExportClipRequest(BaseModel):
    """Request model for exporting a single clip."""

    format: ExportFormat = Field(..., description="Target platform format")
    include_subtitles: bool = Field(default=True, description="Burn subtitles if enabled")


class ExportAllClipsRequest(BaseModel):
    """Request model for batch exporting all clips."""

    format: ExportFormat = Field(..., description="Target platform format")
    include_subtitles: bool = Field(default=True)


class ExportResponse(BaseModel):
    """Response model for export operations."""

    clip_id: str
    status: ClipExportStatus
    export_url: str | None = None
    message: str | None = None


class BatchExportResponse(BaseModel):
    """Response model for batch export."""

    project_id: str
    total_clips: int
    exports: list[ExportResponse]
    message: str


# =============================================================================
# Auto-Clip Generation Models
# =============================================================================


class AutoClipRequest(BaseModel):
    """Request model for generating AI-suggested clips."""

    max_clips: int = Field(default=5, ge=1, le=20, description="Maximum clips to generate")
    min_duration: float = Field(default=15, ge=5, description="Minimum clip duration in seconds")
    max_duration: float = Field(default=60, le=180, description="Maximum clip duration in seconds")
    min_viral_score: float = Field(default=50, ge=0, le=100, description="Minimum viral score threshold")


class AutoClipSuggestion(BaseModel):
    """A suggested clip from AI analysis."""

    start_time: float
    end_time: float
    duration: float
    viral_score: float
    viral_reasons: list[str]
    transcript_snippet: str
    hook_text: str | None = None  # First few words (the hook)


class AutoClipResponse(BaseModel):
    """Response model for auto-clip generation."""

    project_id: str
    suggestions: list[AutoClipSuggestion]
    total_found: int
    message: str


# Update forward references
ProjectWithClips.model_rebuild()
