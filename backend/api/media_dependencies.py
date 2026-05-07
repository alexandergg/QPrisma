"""Media ownership and storage-tiering dependency helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from core.errors import service_unavailable
from models.user import User


def get_storage_tiering_service():
    """Get or create Storage Tiering Service singleton."""
    import api.dependencies as deps

    if deps._storage_tiering_service is None:
        from services.storage_tiering_service import StorageTieringService

        deps._storage_tiering_service = StorageTieringService()
    return deps._storage_tiering_service


def get_storage_route_service():
    """Get or create Storage Route Service singleton."""
    import api.dependencies as deps

    if deps._storage_route_service is None:
        from services.storage_route_service import StorageRouteService

        deps._storage_route_service = StorageRouteService()
    return deps._storage_route_service


def get_media_upload_service(
    *,
    blob_service: Any | None = None,
    db: Any | None = None,
    container_name: str | None = None,
    dispatch_service_factory: Callable[[], Any] | None = None,
):
    """Build the media upload service from centralized API dependencies."""
    import api.dependencies as deps
    from services.media_upload_service import MediaUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    resolved_blob_service = blob_service if blob_service is not None else deps.get_blob_service()
    if not resolved_blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    return MediaUploadService(
        blob_service=resolved_blob_service,
        db=db if db is not None else deps.get_database_service(),
        container_name=container_name if container_name is not None else deps.get_storage_container_name(),
        dispatch_service_factory=dispatch_service_factory or get_video_processing_dispatch_service,
    )


def get_media_library_service(
    *,
    db: Any | None = None,
    blob_service: Any | None = None,
    container_name: str | None = None,
    sas_url_factory: Callable[[str], Awaitable[str | None]] | None = None,
    hydrate_data_factory: Callable[[dict], Awaitable[dict]] | None = None,
    graph_service_factory: Callable[[], Any] | None = None,
):
    """Build the media library service from centralized API dependencies."""
    import api.dependencies as deps
    from services.media_library_service import MediaLibraryService

    return MediaLibraryService(
        db=db if db is not None else deps.get_database_service(),
        blob_service=blob_service if blob_service is not None else deps.get_blob_service(),
        container_name=container_name if container_name is not None else deps.get_storage_container_name(),
        sas_url_factory=sas_url_factory,
        hydrate_data_factory=hydrate_data_factory,
        graph_service_factory=graph_service_factory or deps.get_knowledge_graph_service,
    )


def get_chunked_upload_service(
    *,
    blob_service: Any | None = None,
    db: Any | None = None,
    container_name: str | None = None,
    sas_url_builder: Callable[..., Awaitable[str]] | None = None,
    dispatch_service_factory: Callable[[], Any] | None = None,
):
    """Build the chunked upload service from centralized API dependencies."""
    import api.dependencies as deps
    from services.chunked_upload_service import ChunkedUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    return ChunkedUploadService(
        blob_service=blob_service if blob_service is not None else deps.get_blob_service(),
        db=db if db is not None else deps.get_database_service(),
        container_name=container_name if container_name is not None else deps.get_storage_container_name(),
        sas_url_builder=sas_url_builder or deps.build_blob_sas_url_async,
        dispatch_service_factory=dispatch_service_factory or get_video_processing_dispatch_service,
    )


def get_media_or_404(
    media_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Fetch media and enforce ownership."""
    import api.dependencies as deps

    db = deps.get_database_service()
    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.user_id != current_user.id and (not allow_superuser or not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not authorized")
    return media


def get_user_media_ids(
    current_user: User,
    *,
    processed_only: bool = False,
) -> list[str]:
    """Return the current user's media IDs, optionally restricted to processed items."""
    import api.dependencies as deps

    db = deps.get_database_service()
    return db.get_user_media_ids(current_user.id, processed_only=processed_only)


def get_graph_node_media_or_404(
    node_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Resolve a graph node to its video and enforce media ownership."""
    import api.dependencies as deps

    graph_service = deps.get_knowledge_graph_service()
    video_id = graph_service.get_node_video_id(node_id)
    if not video_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return deps.get_media_or_404(video_id, current_user, allow_superuser=allow_superuser)
