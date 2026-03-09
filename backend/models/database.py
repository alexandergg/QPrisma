"""
SQLAlchemy Database Models for QPrisma

Replaces Cosmos DB with PostgreSQL for:
- Media metadata
- User management
- Job tracking
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def generate_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid4())


class UserModel(Base):
    """User table for authentication."""

    __tablename__ = "users"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    media = relationship("MediaModel", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MediaModel(Base):
    """Media metadata table (videos, images)."""

    __tablename__ = "media"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    blob_name = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=True)
    media_type = Column(String(32), nullable=False, index=True)  # 'video' or 'image'
    file_size = Column(Integer, nullable=True)
    content_type = Column(String(128), nullable=True)

    # Processing status
    processed = Column(Boolean, default=False, index=True)
    processing_status = Column(String(32), default="uploaded", index=True)
    processing_message = Column(Text, nullable=True)
    processing_progress = Column(Float, default=0.0)
    processing_method = Column(String(64), nullable=True)
    job_id = Column(String(64), nullable=True, index=True)

    # Video metadata (JSON)
    video_metadata = Column(JSON, nullable=True)  # duration, fps, resolution, etc.
    processing_result = Column(JSON, nullable=True)  # frames_analyzed, etc.
    audio_data = Column(JSON, nullable=True)  # transcription data

    # Pipeline configuration
    optimized_pipeline = Column(Boolean, default=False)
    pipeline_config = Column(JSON, nullable=True)

    # Blob references for heavy data
    audio_data_blob = Column(String(512), nullable=True)
    objects_data_blob = Column(String(512), nullable=True)
    frames_data_blob = Column(String(512), nullable=True)

    # Timestamps
    upload_date = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_updated = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    last_accessed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )  # For storage tiering

    # Storage tiering
    storage_tier = Column(String(32), default="Hot")  # Hot, Cool, Cold, Archive
    rehydration_status = Column(
        String(32), nullable=True
    )  # rehydrate-pending-to-hot, rehydrate-pending-to-cool

    # Relationships
    user = relationship("UserModel", back_populates="media")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "blob_name": self.blob_name,
            "original_filename": self.original_filename,
            "media_type": self.media_type,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "processed": self.processed,
            "processing_status": self.processing_status,
            "processing_message": self.processing_message,
            "processing_progress": self.processing_progress,
            "processing_method": self.processing_method,
            "job_id": self.job_id,
            "video_metadata": self.video_metadata,
            "processing_result": self.processing_result,
            "audio_data": self.audio_data,
            "optimized_pipeline": self.optimized_pipeline,
            "pipeline_config": self.pipeline_config,
            "audio_data_blob": self.audio_data_blob,
            "objects_data_blob": self.objects_data_blob,
            "frames_data_blob": self.frames_data_blob,
            "upload_date": self.upload_date.isoformat() if self.upload_date else None,
            "uploaded_at": self.upload_date.isoformat() if self.upload_date else None,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "last_accessed_at": (
                self.last_accessed_at.isoformat() if self.last_accessed_at else None
            ),
            "storage_tier": self.storage_tier,
            "rehydration_status": self.rehydration_status,
        }


class JobModel(Base):
    """Background job tracking table."""

    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)  # Celery task ID
    media_id = Column(String(64), ForeignKey("media.id"), nullable=True, index=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    job_type = Column(String(64), nullable=False)  # 'video_processing', 'embedding', etc.
    status = Column(String(32), default="pending", index=True)
    progress = Column(Float, default=0.0)
    message = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media_id": self.media_id,
            "user_id": self.user_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class EditorProjectModel(Base):
    """Editor project for video editing.

    A project represents an editing session for a source video,
    containing multiple clips that form the final output.
    """

    __tablename__ = "editor_projects"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    source_media_id = Column(String(64), ForeignKey("media.id"), nullable=False, index=True)

    # Project metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Status: draft, exporting, completed, archived
    status = Column(String(32), default="draft", index=True)

    # Project settings (format, resolution, etc.)
    settings = Column(JSON, nullable=True, default=dict)

    # Export info
    export_format = Column(String(32), nullable=True)  # tiktok, reels, shorts, youtube
    export_url = Column(String(512), nullable=True)  # Final exported video URL

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    clips = relationship(
        "ClipModel",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ClipModel.order",
    )
    source_media = relationship("MediaModel")

    def to_dict(self) -> dict[str, Any]:
        # Safe access to clips - avoid lazy load if detached from session
        from sqlalchemy.orm import object_session
        from sqlalchemy.orm.attributes import instance_state

        clips_count = 0
        state = instance_state(self)
        if "clips" in state.dict:
            # Clips already loaded
            clips_count = len(self.clips) if self.clips else 0
        elif object_session(self) is not None:
            # Still in session, can lazy load
            clips_count = len(self.clips) if self.clips else 0
        # If detached and not loaded, clips_count stays 0

        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_media_id": self.source_media_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "settings": self.settings,
            "export_format": self.export_format,
            "export_url": self.export_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "clips_count": clips_count,
        }


class ClipModel(Base):
    """Clip within an editor project.

    Represents a segment of the source video that will be
    included in the final export.
    """

    __tablename__ = "clips"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("editor_projects.id"), nullable=False, index=True)

    # Timing (in seconds)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)

    # Position in timeline
    order = Column(Integer, nullable=False, default=0)

    # Clip metadata
    title = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    # AI metadata
    is_ai_suggested = Column(Boolean, default=False)
    viral_score = Column(Float, nullable=True)  # 0-100
    viral_reasons = Column(JSON, nullable=True)  # ["hook", "high_energy", ...]
    transcript_snippet = Column(Text, nullable=True)  # Text from this segment

    # Subtitle configuration
    subtitle_style = Column(String(32), nullable=True)  # hormozi, mrbeast, minimal, karaoke, news
    subtitles_enabled = Column(Boolean, default=False)
    subtitles_data = Column(JSON, nullable=True)  # Parsed SRT data with word timings
    subtitle_settings = Column(JSON, nullable=True)  # font, color, position, etc.

    # Export status for individual clip
    export_status = Column(String(32), default="pending")  # pending, processing, done, failed
    export_url = Column(String(512), nullable=True)  # URL of exported clip
    export_format = Column(String(32), nullable=True)  # tiktok, reels, etc.

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    project = relationship("EditorProjectModel", back_populates="clips")

    @property
    def duration(self) -> float:
        """Calculate clip duration in seconds."""
        return self.end_time - self.start_time

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "order": self.order,
            "title": self.title,
            "notes": self.notes,
            "is_ai_suggested": self.is_ai_suggested,
            "viral_score": self.viral_score,
            "viral_reasons": self.viral_reasons,
            "transcript_snippet": self.transcript_snippet,
            "subtitle_style": self.subtitle_style,
            "subtitles_enabled": self.subtitles_enabled,
            "subtitles_data": self.subtitles_data,
            "subtitle_settings": self.subtitle_settings,
            "export_status": self.export_status,
            "export_url": self.export_url,
            "export_format": self.export_format,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BatchJobModel(Base):
    """Azure OpenAI Batch API job tracking.

    Tracks batch jobs for vision analysis and embeddings.
    Enables 50% cost savings on OpenAI API calls.
    """

    __tablename__ = "batch_jobs"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    azure_batch_id = Column(String(128), nullable=False, unique=True, index=True)
    media_id = Column(String(64), ForeignKey("media.id"), nullable=True, index=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=True, index=True)

    # Batch type: 'vision', 'embedding', 'chat'
    batch_type = Column(String(32), nullable=False, index=True)

    # Status: 'validating', 'in_progress', 'finalizing', 'completed', 'failed', 'expired', 'cancelled'
    status = Column(String(32), default="validating", index=True)

    # Request counts
    total_requests = Column(Integer, default=0)
    completed_requests = Column(Integer, default=0)
    failed_requests = Column(Integer, default=0)

    # File IDs
    input_file_id = Column(String(128), nullable=True)
    output_file_id = Column(String(128), nullable=True)
    error_file_id = Column(String(128), nullable=True)

    # Cost tracking
    estimated_cost = Column(Float, nullable=True)  # Estimated cost in USD
    actual_cost = Column(Float, nullable=True)  # Actual cost after completion
    tokens_used = Column(Integer, default=0)

    # Metadata
    description = Column(Text, nullable=True)
    batch_metadata = Column(JSON, nullable=True)  # Custom metadata

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # 24h window

    # Error handling
    error_message = Column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "azure_batch_id": self.azure_batch_id,
            "media_id": self.media_id,
            "user_id": self.user_id,
            "batch_type": self.batch_type,
            "status": self.status,
            "total_requests": self.total_requests,
            "completed_requests": self.completed_requests,
            "failed_requests": self.failed_requests,
            "input_file_id": self.input_file_id,
            "output_file_id": self.output_file_id,
            "error_file_id": self.error_file_id,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "tokens_used": self.tokens_used,
            "description": self.description,
            "batch_metadata": self.batch_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error_message": self.error_message,
            "progress_percent": round(
                (
                    (self.completed_requests / self.total_requests * 100)
                    if self.total_requests > 0
                    else 0
                ),
                1,
            ),
        }


class ToolArtifactModel(Base):
    """Metadata index for full tool output artifacts."""

    __tablename__ = "tool_artifacts"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    tool_call_id = Column(String(128), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False, index=True)

    # Scope / ownership
    session_id = Column(String(128), nullable=False, index=True)
    thread_id = Column(String(128), nullable=True, index=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    media_id = Column(String(64), ForeignKey("media.id"), nullable=True, index=True)
    project_id = Column(String(64), ForeignKey("editor_projects.id"), nullable=True, index=True)

    # Durable payload reference
    blob_name = Column(String(512), nullable=False, unique=True)
    content_type = Column(String(128), nullable=False, default="application/json")
    content_encoding = Column(String(32), nullable=False, default="gzip")

    # Size and integrity
    size_bytes = Column(Integer, nullable=False)
    compressed_size_bytes = Column(Integer, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False, index=True)

    # Arbitrary metadata for debugging/traceability
    artifact_metadata = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    last_accessed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "media_id": self.media_id,
            "project_id": self.project_id,
            "blob_name": self.blob_name,
            "content_type": self.content_type,
            "content_encoding": self.content_encoding,
            "size_bytes": self.size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "checksum_sha256": self.checksum_sha256,
            "artifact_metadata": self.artifact_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_accessed_at": (
                self.last_accessed_at.isoformat() if self.last_accessed_at else None
            ),
        }


class A2ATaskModel(Base):
    """Persistent A2A task state for multi-instance durability and recovery."""

    __tablename__ = "a2a_tasks"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    context_id = Column(String(128), nullable=False, index=True)

    status_state = Column(String(64), nullable=False, index=True)
    status_timestamp = Column(DateTime, nullable=True, index=True)
    status_payload = Column(JSON, nullable=False)

    artifacts = Column(JSON, nullable=True)
    history = Column(JSON, nullable=True)
    task_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "context_id": self.context_id,
            "status_state": self.status_state,
            "status_timestamp": (
                self.status_timestamp.isoformat() if self.status_timestamp else None
            ),
            "status_payload": self.status_payload,
            "artifacts": self.artifacts,
            "history": self.history,
            "task_metadata": self.task_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
