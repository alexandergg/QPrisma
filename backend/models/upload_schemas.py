"""Schemas for media and chunked upload API responses."""

from typing import Any

from pydantic import BaseModel, Field


class MediaUploadResponse(BaseModel):
    """Response returned after a direct media upload."""

    media_id: str
    blob_name: str
    media_type: str
    file_size: int = Field(..., ge=0)
    job_id: str | None = None
    status: str | None = None
    message: str
    pipeline: str | None = None


class ChunkedUploadStatusResponse(BaseModel):
    """Current resumable upload status."""

    media_id: str
    upload_id: str | None = None
    status: str
    message: str | None = None
    total_blocks: int | None = None
    uploaded_blocks: int | None = None
    uploaded_block_ids: list[str] = Field(default_factory=list)
    remaining_blocks: list[dict[str, Any]] = Field(default_factory=list)


class CancelUploadResponse(BaseModel):
    """Response returned after cancelling a chunked upload."""

    message: str
    media_id: str


class StorageHealthResponse(BaseModel):
    """Public storage health response with internal details redacted."""

    status: str
    service: str
    message: str | None = None
