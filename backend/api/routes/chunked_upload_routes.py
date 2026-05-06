"""
Chunked Upload Routes

High-performance upload endpoints for large files (1GB+) using:
- Block-based parallel uploads via Azure Blob Storage Stage/Commit
- Direct-to-blob uploads with SAS tokens
- Progress tracking and resumable uploads
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import (
    build_blob_sas_url_async,
    get_blob_service,
    get_current_user,
    get_storage_container_name,
)
from models.user import User
from services.chunked_upload_service import (
    DEFAULT_BLOCK_SIZE_MB,
    ChunkedUploadService,
)
from services.database_service import get_database_service
from services.video_processing_dispatch_service import get_video_processing_dispatch_service

router = APIRouter(prefix="/upload/chunked", tags=["Chunked Upload"])
logger = logging.getLogger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class InitUploadRequest(BaseModel):
    """Request to initialize a chunked upload."""

    filename: str
    file_size: int  # Total file size in bytes
    content_type: str = "video/mp4"
    block_size_mb: int = DEFAULT_BLOCK_SIZE_MB  # Block size in MB


class InitUploadResponse(BaseModel):
    """Response with upload session details."""

    upload_id: str
    media_id: str
    blob_name: str
    block_size: int  # Block size in bytes
    total_blocks: int
    upload_url: str  # SAS URL for direct upload
    sas_expiry: str
    blocks: list[dict]  # List of block IDs and their upload URLs


class CommitUploadRequest(BaseModel):
    """Request to commit/finalize a chunked upload."""

    upload_id: str
    media_id: str
    blob_name: str
    block_ids: list[str]  # Ordered list of block IDs to commit
    preset: str = "balanced"
    max_frames: int = 150
    use_scene_detection: bool = True
    use_hierarchical_summary: bool = True


class CommitUploadResponse(BaseModel):
    """Response after successful commit."""

    media_id: str
    blob_name: str
    file_size: int
    job_id: str | None
    status: str
    message: str


class BlockUploadUrl(BaseModel):
    """URL for uploading a single block."""

    block_id: str
    block_index: int
    upload_url: str


def get_chunked_upload_service_instance() -> ChunkedUploadService:
    return ChunkedUploadService(
        blob_service=get_blob_service(),
        db=get_database_service(),
        container_name=get_storage_container_name(),
        sas_url_builder=build_blob_sas_url_async,
        dispatch_service_factory=get_video_processing_dispatch_service,
    )


# =============================================================================
# Routes
# =============================================================================


@router.post("/init", response_model=InitUploadResponse)
async def init_chunked_upload(
    request: InitUploadRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Initialize a chunked upload session.

    Returns:
    - upload_id: Unique session identifier
    - media_id: The ID that will be used for this media
    - block_size: Size of each block in bytes
    - total_blocks: Number of blocks to upload
    - upload_url: Base SAS URL for uploading blocks
    - blocks: List of block IDs to use for each chunk

    The client should:
    1. Split the file into blocks of block_size bytes
    2. Upload each block to: {upload_url}&comp=block&blockid={base64_block_id}
    3. Call /commit with the ordered list of block_ids
    """
    service = get_chunked_upload_service_instance()
    return InitUploadResponse(
        **await service.init_upload(
            filename=request.filename,
            file_size=request.file_size,
            content_type=request.content_type,
            block_size_mb=request.block_size_mb,
            user_id=current_user.id,
        )
    )


@router.post("/commit", response_model=CommitUploadResponse)
async def commit_chunked_upload(
    request: CommitUploadRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Commit/finalize a chunked upload.

    After all blocks are uploaded, call this to:
    1. Commit the block list to create the final blob
    2. Update media record
    3. Start video processing

    Args:
        block_ids: Ordered list of block IDs (base64 encoded) that were uploaded
    """
    service = get_chunked_upload_service_instance()
    return CommitUploadResponse(
        **await service.commit_upload(
            media_id=request.media_id,
            blob_name=request.blob_name,
            block_ids=request.block_ids,
            preset=request.preset,
            max_frames=request.max_frames,
            use_scene_detection=request.use_scene_detection,
            use_hierarchical_summary=request.use_hierarchical_summary,
            user_id=current_user.id,
        )
    )


@router.get("/status/{media_id}")
async def get_upload_status(
    media_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get the status of a chunked upload.

    Returns information about which blocks have been uploaded
    (useful for resuming interrupted uploads).
    """
    service = get_chunked_upload_service_instance()
    return service.get_status(media_id=media_id, user_id=current_user.id)


@router.delete("/cancel/{media_id}")
async def cancel_upload(
    media_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel an in-progress chunked upload.

    Deletes any uploaded blocks and the media record.
    """
    service = get_chunked_upload_service_instance()
    return service.cancel_upload(media_id=media_id, user_id=current_user.id)
