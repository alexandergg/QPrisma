"""
Chunked Upload Routes

High-performance upload endpoints for large files (1GB+) using:
- Block-based parallel uploads via Azure Blob Storage Stage/Commit
- Direct-to-blob uploads with SAS tokens
- Progress tracking and resumable uploads
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from azure.storage.blob import (
    BlobBlock,
    BlobSasPermissions,
    BlobType,
    generate_blob_sas,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.dependencies import (
    get_blob_service,
    get_current_user,
    get_storage_account_info,
    get_storage_container_name,
)
from models.user import User
from services.database_service import get_database_service

router = APIRouter(prefix="/upload/chunked", tags=["Chunked Upload"])
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Recommended block size for optimal throughput (8MB-100MB based on bandwidth)
DEFAULT_BLOCK_SIZE_MB = 8
MAX_BLOCK_SIZE_MB = 100
MAX_BLOCKS = 50000  # Azure limit
MAX_FILE_SIZE_GB = 190  # Azure block blob limit ~190GB


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


# =============================================================================
# Helper Functions
# =============================================================================


def generate_block_id(index: int) -> str:
    """Generate a unique block ID for Azure Blob Storage.
    
    Block IDs must be base64-encoded and have consistent length.
    """
    import base64
    # Format: 6-digit padded index for sorting + 8 random chars for uniqueness
    block_id = f"{index:06d}-{uuid.uuid4().hex[:8]}"
    return base64.b64encode(block_id.encode()).decode()


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
    blob_service = get_blob_service()
    if not blob_service:
        raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")

    # Validate file size
    max_size = MAX_FILE_SIZE_GB * 1024 * 1024 * 1024
    if request.file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_GB}GB"
        )

    # Validate block size
    block_size_mb = min(max(request.block_size_mb, 1), MAX_BLOCK_SIZE_MB)
    block_size_bytes = block_size_mb * 1024 * 1024

    # Calculate number of blocks
    total_blocks = (request.file_size + block_size_bytes - 1) // block_size_bytes
    if total_blocks > MAX_BLOCKS:
        # Increase block size to stay under limit
        block_size_bytes = (request.file_size + MAX_BLOCKS - 1) // MAX_BLOCKS
        total_blocks = (request.file_size + block_size_bytes - 1) // block_size_bytes

    # Generate IDs
    upload_id = str(uuid.uuid4())
    media_id = str(uuid.uuid4())
    
    # Determine file extension
    file_extension = request.filename.split(".")[-1].lower() if "." in request.filename else "mp4"
    blob_name = f"{media_id}.{file_extension}"

    # Generate block IDs
    blocks = []
    for i in range(total_blocks):
        block_id = generate_block_id(i)
        blocks.append({
            "block_id": block_id,
            "block_index": i,
        })

    # Generate SAS URL for upload
    account_info = get_storage_account_info()
    if not account_info:
        raise HTTPException(status_code=503, detail="Cannot generate SAS token")

    account_name, account_key, container_name = account_info
    
    sas_expiry = datetime.now(UTC) + timedelta(hours=4)
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True, read=True),
        expiry=sas_expiry,
    )
    
    upload_url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"

    # Store upload session in database (for resumability)
    db = get_database_service()
    try:
        # Create media record with pending status
        media_data = {
            "id": media_id,
            "user_id": current_user.id,
            "blob_name": blob_name,
            "original_filename": request.filename,
            "media_type": "video",
            "file_size": request.file_size,
            "content_type": request.content_type,
            "processing_status": "uploading",
            "upload_session": {
                "upload_id": upload_id,
                "total_blocks": total_blocks,
                "block_size": block_size_bytes,
                "blocks": blocks,
                "started_at": datetime.now(UTC).isoformat(),
            },
        }
        db.create_media(media_data)
    except Exception as e:
        logger.error(f"Failed to create media record: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize upload")

    logger.info(
        f"Initialized chunked upload: {upload_id}, "
        f"file={request.filename}, size={request.file_size}, "
        f"blocks={total_blocks}, block_size={block_size_bytes}"
    )

    return InitUploadResponse(
        upload_id=upload_id,
        media_id=media_id,
        blob_name=blob_name,
        block_size=block_size_bytes,
        total_blocks=total_blocks,
        upload_url=upload_url,
        sas_expiry=sas_expiry.isoformat(),
        blocks=blocks,
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
    blob_service = get_blob_service()
    db = get_database_service()

    if not blob_service:
        raise HTTPException(status_code=503, detail="Azure Blob Storage not configured")

    # Verify media exists and belongs to user
    media = db.get_media(request.media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if media.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    container_name = get_storage_container_name()
    
    try:
        # Get blob client
        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=request.blob_name,
        )

        # Commit the block list
        # Azure requires BlobBlock objects for the commit
        block_list = [BlobBlock(block_id=bid) for bid in request.block_ids]
        
        blob_client.commit_block_list(
            block_list=block_list,
            blob_type=BlobType.BLOCKBLOB,
        )

        # Get final blob properties
        props = blob_client.get_blob_properties()
        final_size = props.size

        logger.info(
            f"Committed blob: {request.blob_name}, "
            f"blocks={len(request.block_ids)}, size={final_size}"
        )

    except Exception as e:
        logger.error(f"Failed to commit blob: {e}")
        db.update_media(request.media_id, {"processing_status": "error"})
        raise HTTPException(status_code=500, detail=f"Failed to commit upload: {str(e)}")

    # Update media record
    pipeline_config = {
        "use_scene_detection": request.use_scene_detection,
        "use_hierarchical_summary": request.use_hierarchical_summary,
    }

    db.update_media(request.media_id, {
        "file_size": final_size,
        "processing_status": "queued",
        "optimized_pipeline": True,
        "pipeline_config": pipeline_config,
        "upload_session": None,  # Clear upload session
    })

    # Queue processing in Celery
    job_id = None
    try:
        from tasks.video_tasks import process_video_pipeline

        celery_config = {
            "max_frames": min(request.max_frames, 500),
            "custom_prompt": None,
            "index_graph": True,
            "preset": request.preset,
            "optimized_pipeline": True,
            "pipeline_config": pipeline_config,
        }
        async_result = process_video_pipeline.apply_async(
            args=[request.media_id, request.blob_name, celery_config]
        )
        job_id = async_result.id

        db.update_media(request.media_id, {"job_id": job_id})

    except Exception as e:
        logger.warning(f"Celery not available: {e}")
        # Still return success - file is uploaded, just not processed

    return CommitUploadResponse(
        media_id=request.media_id,
        blob_name=request.blob_name,
        file_size=final_size,
        job_id=job_id,
        status="queued" if job_id else "uploaded",
        message="Upload complete. Processing queued." if job_id else "Upload complete.",
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
    db = get_database_service()
    blob_service = get_blob_service()

    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Upload not found")
    if media.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    upload_session = media.upload_session if hasattr(media, 'upload_session') else None
    
    if not upload_session:
        return {
            "media_id": media_id,
            "status": media.processing_status,
            "message": "Upload already completed or not using chunked upload",
        }

    # Check which blocks have been uploaded
    container_name = get_storage_container_name()
    blob_client = blob_service.get_blob_client(
        container=container_name,
        blob=media.blob_name,
    )

    try:
        # Get uncommitted block list
        block_list = blob_client.get_block_list(block_list_type="uncommitted")
        uploaded_block_ids = {block.id for block in block_list.uncommitted_blocks}
    except Exception:
        uploaded_block_ids = set()

    return {
        "media_id": media_id,
        "upload_id": upload_session.get("upload_id"),
        "status": "uploading",
        "total_blocks": upload_session.get("total_blocks"),
        "uploaded_blocks": len(uploaded_block_ids),
        "uploaded_block_ids": list(uploaded_block_ids),
        "remaining_blocks": [
            b for b in upload_session.get("blocks", [])
            if b["block_id"] not in uploaded_block_ids
        ],
    }


@router.delete("/cancel/{media_id}")
async def cancel_upload(
    media_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel an in-progress chunked upload.
    
    Deletes any uploaded blocks and the media record.
    """
    db = get_database_service()
    blob_service = get_blob_service()

    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Upload not found")
    if media.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Try to delete the blob (uncommitted blocks are auto-deleted after 7 days)
    container_name = get_storage_container_name()
    try:
        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=media.blob_name,
        )
        blob_client.delete_blob()
    except Exception:
        pass  # Blob may not exist yet

    # Delete media record
    db.delete_media(media_id)

    return {"message": "Upload cancelled", "media_id": media_id}
