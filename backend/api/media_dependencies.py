"""Media ownership and storage-tiering dependency helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from core.errors import service_unavailable
from models.user import User

_storage_tiering_service = None
_storage_route_service = None


def _default_blob_service_factory():
    from api.azure_dependencies import get_blob_service

    return get_blob_service()


def _default_storage_container_name_factory() -> str:
    from api.azure_dependencies import get_storage_container_name

    return get_storage_container_name()


def _default_database_service_factory():
    from services.database_service import get_database_service

    return get_database_service()


def get_storage_tiering_service():
    """Get or create Storage Tiering Service singleton."""
    global _storage_tiering_service

    if _storage_tiering_service is None:
        from services.storage_tiering_service import StorageTieringService

        _storage_tiering_service = StorageTieringService()
    return _storage_tiering_service


def get_storage_route_service():
    """Get or create Storage Route Service singleton."""
    global _storage_route_service

    if _storage_route_service is None:
        from services.storage_route_service import StorageRouteService

        _storage_route_service = StorageRouteService()
    return _storage_route_service


def get_media_upload_service(
    *,
    blob_service: Any | None = None,
    db: Any | None = None,
    container_name: str | None = None,
    dispatch_service_factory: Callable[[], Any] | None = None,
    blob_service_factory: Callable[[], Any] | None = None,
    db_factory: Callable[[], Any] | None = None,
    container_name_factory: Callable[[], str] | None = None,
):
    """Build the media upload service from centralized API dependencies."""
    from services.media_upload_service import MediaUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    blob_service_factory = blob_service_factory or _default_blob_service_factory
    db_factory = db_factory or _default_database_service_factory
    container_name_factory = container_name_factory or _default_storage_container_name_factory

    resolved_blob_service = blob_service if blob_service is not None else blob_service_factory()
    if not resolved_blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    return MediaUploadService(
        blob_service=resolved_blob_service,
        db=db if db is not None else db_factory(),
        container_name=container_name if container_name is not None else container_name_factory(),
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
    db_factory: Callable[[], Any] | None = None,
    blob_service_factory: Callable[[], Any] | None = None,
    container_name_factory: Callable[[], str] | None = None,
):
    """Build the media library service from centralized API dependencies."""
    from services.media_library_service import MediaLibraryService

    db_factory = db_factory or _default_database_service_factory
    blob_service_factory = blob_service_factory or _default_blob_service_factory
    container_name_factory = container_name_factory or _default_storage_container_name_factory
    if graph_service_factory is None:
        from api.graph_dependencies import get_knowledge_graph_service as graph_service_factory

    return MediaLibraryService(
        db=db if db is not None else db_factory(),
        blob_service=blob_service if blob_service is not None else blob_service_factory(),
        container_name=container_name if container_name is not None else container_name_factory(),
        sas_url_factory=sas_url_factory,
        hydrate_data_factory=hydrate_data_factory,
        graph_service_factory=graph_service_factory,
    )


def get_chunked_upload_service(
    *,
    blob_service: Any | None = None,
    db: Any | None = None,
    container_name: str | None = None,
    sas_url_builder: Callable[..., Awaitable[str]] | None = None,
    dispatch_service_factory: Callable[[], Any] | None = None,
    blob_service_factory: Callable[[], Any] | None = None,
    db_factory: Callable[[], Any] | None = None,
    container_name_factory: Callable[[], str] | None = None,
):
    """Build the chunked upload service from centralized API dependencies."""
    from services.chunked_upload_service import ChunkedUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    blob_service_factory = blob_service_factory or _default_blob_service_factory
    db_factory = db_factory or _default_database_service_factory
    container_name_factory = container_name_factory or _default_storage_container_name_factory
    if sas_url_builder is None:
        from api.azure_dependencies import build_blob_sas_url_async as sas_url_builder

    return ChunkedUploadService(
        blob_service=blob_service if blob_service is not None else blob_service_factory(),
        db=db if db is not None else db_factory(),
        container_name=container_name if container_name is not None else container_name_factory(),
        sas_url_builder=sas_url_builder,
        dispatch_service_factory=dispatch_service_factory or get_video_processing_dispatch_service,
    )


def get_media_or_404(
    media_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
    db_factory: Callable[[], Any] | None = None,
):
    """Fetch media and enforce ownership."""
    db_factory = db_factory or _default_database_service_factory
    db = db_factory()
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
    db_factory: Callable[[], Any] | None = None,
) -> list[str]:
    """Return the current user's media IDs, optionally restricted to processed items."""
    db_factory = db_factory or _default_database_service_factory
    db = db_factory()
    return db.get_user_media_ids(current_user.id, processed_only=processed_only)


def get_graph_node_media_or_404(
    node_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
    graph_service_factory: Callable[[], Any] | None = None,
    media_getter: Callable[..., Any] | None = None,
):
    """Resolve a graph node to its video and enforce media ownership."""
    if graph_service_factory is None:
        from api.graph_dependencies import get_knowledge_graph_service as graph_service_factory

    media_getter = media_getter or get_media_or_404
    graph_service = graph_service_factory()
    video_id = graph_service.get_node_video_id(node_id)
    if not video_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return media_getter(video_id, current_user, allow_superuser=allow_superuser)
