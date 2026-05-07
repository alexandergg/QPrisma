"""Shared dependency facade for API routes and tests."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from functools import partial

from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
from fastapi import HTTPException
from openai import AsyncAzureOpenAI, AzureOpenAI

from api.auth_dependencies import (
    get_current_user,
    get_current_user_optional,
    require_benchmark_operator,
    require_superuser,
    security,
    security_optional,
)
from core.azure_credentials import (
    build_openai_client_kwargs,
    create_blob_service_client,
    uses_managed_identity_storage,
)
from core.config import settings
from core.errors import service_unavailable
from services.database_service import get_database_service

logger = logging.getLogger(__name__)

_blob_service: BlobServiceClient | None = None
_openai_client: AzureOpenAI | None = None
_async_openai_client: AsyncAzureOpenAI | None = None
_knowledge_graph_service = None
_graph_route_service = None
_hierarchical_context_service = None
_community_detection_service = None
_hierarchical_query_service = None
_storage_tiering_service = None
_storage_route_service = None


def get_blob_service():
    """Get or create Blob Storage client with optimized transfer settings."""
    global _blob_service

    if _blob_service is None:
        _blob_service = create_blob_service_client(
            storage_connection_string=settings.azure.storage_connection_string,
            storage_account_url=settings.azure.storage_account_url,
            use_managed_identity=settings.azure.use_managed_identity,
            max_single_put_size=256 * 1024 * 1024,
            max_block_size=100 * 1024 * 1024,
            max_concurrency=8,
        )
    return _blob_service


def get_openai_client():
    """Get or create Azure OpenAI client (sync)."""
    global _openai_client

    if _openai_client is None:
        client_kwargs = build_openai_client_kwargs(
            endpoint=settings.azure.openai_endpoint,
            api_key=settings.azure.openai_api_key,
            api_version=settings.azure.openai_api_version,
            use_managed_identity=settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            _openai_client = AzureOpenAI(**client_kwargs)
    return _openai_client


def get_async_openai_client():
    """Get or create Azure OpenAI client (async)."""
    global _async_openai_client

    if _async_openai_client is None:
        client_kwargs = build_openai_client_kwargs(
            endpoint=settings.azure.openai_endpoint,
            api_key=settings.azure.openai_api_key,
            api_version=settings.azure.openai_api_version,
            use_managed_identity=settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            _async_openai_client = AsyncAzureOpenAI(**client_kwargs)
    return _async_openai_client


def get_storage_container_name() -> str:
    """Get Azure Storage container name for media."""
    return settings.azure.storage_container_name


def get_storage_account_info() -> tuple[str, str, str] | None:
    """Extract (account_name, account_key, container_name) from connection string."""
    conn_string = settings.azure.storage_connection_string or ""
    account_name_match = re.search(r"AccountName=([^;]+)", conn_string)
    account_key_match = re.search(r"AccountKey=([^;]+)", conn_string)

    if not (account_name_match and account_key_match):
        return None

    return (
        account_name_match.group(1),
        account_key_match.group(1),
        get_storage_container_name(),
    )


def build_blob_sas_url(
    blob_name: str,
    *,
    permission: BlobSasPermissions,
    expiry: datetime,
    start: datetime | None = None,
    container_name: str | None = None,
) -> str | None:
    """Build a blob SAS URL using managed identity or local fallback credentials."""
    blob_service = get_blob_service()
    if not blob_service:
        return None

    resolved_container = container_name or get_storage_container_name()
    blob_client = blob_service.get_blob_client(container=resolved_container, blob=blob_name)
    start_time = start or (datetime.now(UTC) - timedelta(minutes=5))

    if uses_managed_identity_storage(
        use_managed_identity=settings.azure.use_managed_identity,
        storage_account_url=settings.azure.storage_account_url,
        storage_connection_string=settings.azure.storage_connection_string,
    ):
        user_delegation_key = blob_service.get_user_delegation_key(
            key_start_time=start_time,
            key_expiry_time=expiry,
        )
        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=resolved_container,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=permission,
            start=start_time,
            expiry=expiry,
        )
        return f"{blob_client.url}?{sas_token}"

    account_info = get_storage_account_info()
    if not account_info:
        return None

    account_name, account_key, _ = account_info
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=resolved_container,
        blob_name=blob_name,
        account_key=account_key,
        permission=permission,
        start=start_time,
        expiry=expiry,
    )
    return f"{blob_client.url}?{sas_token}"


async def build_blob_sas_url_async(
    blob_name: str,
    *,
    permission: BlobSasPermissions,
    expiry: datetime,
    start: datetime | None = None,
    container_name: str | None = None,
) -> str | None:
    """Build a blob SAS URL without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(
            build_blob_sas_url,
            blob_name,
            permission=permission,
            expiry=expiry,
            start=start,
            container_name=container_name,
        ),
    )


def _get_storage_route_service_singleton():
    """Get or create the cached StorageRouteService instance."""
    global _storage_route_service

    if _storage_route_service is None:
        from services.storage_route_service import StorageRouteService

        _storage_route_service = StorageRouteService()
    return _storage_route_service


async def _default_media_library_sas_url(blob_name: str, expiry_hours: int) -> str | None:
    return await build_blob_sas_url_async(
        blob_name,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(UTC) + timedelta(hours=expiry_hours),
    )


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service, ensuring it is connected."""
    global _knowledge_graph_service

    if _knowledge_graph_service is None:
        from services.knowledge_graph import (
            get_knowledge_graph_service as _get_kg_service,
        )

        _knowledge_graph_service = _get_kg_service()
        if not _knowledge_graph_service.is_connected:
            _knowledge_graph_service.connect()
    return _knowledge_graph_service


def get_async_graph_service():
    """Return the non-blocking AsyncKnowledgeGraphFacade singleton."""
    from services.async_graph_facade import get_async_knowledge_graph_facade

    return get_async_knowledge_graph_facade()


def get_graph_search_service():
    """Get or create Graph Search Service (VideoRAG-style hybrid search)."""
    from services.graph_search_service import (
        get_graph_search_service as _canonical_getter,
    )

    return _canonical_getter()


def get_chat_service(*, openai_client=None, graph_search_service=None, service_cls=None):
    """Build ChatService while preserving facade-level patch points."""
    from services.chat_service import ChatService

    if openai_client is None:
        openai_client = get_async_openai_client()
    if graph_search_service is None:
        graph_search_service = get_graph_search_service()

    resolved_service_cls = service_cls or ChatService
    return resolved_service_cls(
        openai_client=openai_client,
        graph_search_service=graph_search_service,
    )


def get_structure_service(*, graph_service=None, service_cls=None):
    """Build StructureService while preserving facade-level patch points."""
    from services.structure_service import StructureService

    resolved_graph_service = (
        graph_service if graph_service is not None else get_knowledge_graph_service()
    )
    resolved_service_cls = service_cls or StructureService
    return resolved_service_cls(graph_service=resolved_graph_service)


def get_graph_route_service():
    """Get or create GraphRouteService while preserving facade-level patch points."""
    global _graph_route_service

    if _graph_route_service is None:
        from services.graph_route_service import GraphRouteService

        _graph_route_service = GraphRouteService(
            knowledge_graph_service=get_knowledge_graph_service(),
            graph_search_service=get_graph_search_service(),
        )
    return _graph_route_service


def get_hierarchical_context_service():
    """Get or create HierarchicalContextService via the stable facade."""
    global _hierarchical_context_service

    if _hierarchical_context_service is None:
        from services.embedding_service import get_embedding_service
        from services.hierarchical_context_service import (
            get_hierarchical_context_service as _get_hcs,
        )

        _hierarchical_context_service = _get_hcs(
            graph_service=get_knowledge_graph_service(),
            embedding_service=get_embedding_service(),
        )
    return _hierarchical_context_service


def get_hierarchical_query_service():
    """Get or create HierarchicalQueryService via the stable facade."""
    global _hierarchical_query_service

    if _hierarchical_query_service is None:
        from services.hierarchical_query_service import (
            get_hierarchical_query_service as _get_hqs,
        )

        _hierarchical_query_service = _get_hqs()
    return _hierarchical_query_service


def get_community_detection_service():
    """Get or create CommunityDetectionService via the stable facade."""
    global _community_detection_service

    if _community_detection_service is None:
        from services.community_detection_service import (
            get_community_detection_service as _get_cds,
        )

        _community_detection_service = _get_cds()
    return _community_detection_service


async def get_tool_artifact_service():
    """Get ToolArtifactService singleton."""
    from services.tool_artifact_service import (
        get_tool_artifact_service as _get_tool_artifact_service,
    )

    return await _get_tool_artifact_service()


def get_storage_tiering_service():
    """Get or create StorageTieringService via the stable facade."""
    global _storage_tiering_service

    if _storage_tiering_service is None:
        from services.storage_tiering_service import StorageTieringService

        _storage_tiering_service = StorageTieringService()
    return _storage_tiering_service


def get_storage_route_service():
    """Get or create StorageRouteService via the stable facade."""
    return _get_storage_route_service_singleton()


def get_media_upload_service(
    *, blob_service=None, db=None, container_name=None, dispatch_service_factory=None
):
    """Build MediaUploadService while preserving facade-level patch points."""
    from services.media_upload_service import MediaUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    resolved_blob_service = blob_service if blob_service is not None else get_blob_service()
    if not resolved_blob_service:
        raise service_unavailable("Azure Blob Storage not configured")

    return MediaUploadService(
        blob_service=resolved_blob_service,
        db=db if db is not None else get_database_service(),
        container_name=(
            container_name if container_name is not None else get_storage_container_name()
        ),
        dispatch_service_factory=dispatch_service_factory or get_video_processing_dispatch_service,
    )


def get_media_library_service(
    *,
    db=None,
    blob_service=None,
    container_name=None,
    sas_url_factory=None,
    hydrate_data_factory=None,
    graph_service_factory=None,
):
    """Build MediaLibraryService while preserving facade-level patch points."""
    from services.media_library_service import MediaLibraryService

    return MediaLibraryService(
        db=db if db is not None else get_database_service(),
        blob_service=blob_service if blob_service is not None else get_blob_service(),
        container_name=(
            container_name if container_name is not None else get_storage_container_name()
        ),
        sas_url_factory=sas_url_factory or _default_media_library_sas_url,
        hydrate_data_factory=hydrate_data_factory,
        graph_service_factory=graph_service_factory or get_knowledge_graph_service,
    )


def get_chunked_upload_service(
    *,
    blob_service=None,
    db=None,
    container_name=None,
    sas_url_builder=None,
    dispatch_service_factory=None,
):
    """Build ChunkedUploadService while preserving facade-level patch points."""
    from services.chunked_upload_service import ChunkedUploadService
    from services.video_processing_dispatch_service import get_video_processing_dispatch_service

    return ChunkedUploadService(
        blob_service=blob_service if blob_service is not None else get_blob_service(),
        db=db if db is not None else get_database_service(),
        container_name=(
            container_name if container_name is not None else get_storage_container_name()
        ),
        sas_url_builder=sas_url_builder or build_blob_sas_url_async,
        dispatch_service_factory=dispatch_service_factory or get_video_processing_dispatch_service,
    )


def get_media_or_404(media_id, current_user, *, allow_superuser=True):
    """Fetch media and enforce ownership through the stable facade."""
    db = get_database_service()
    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.user_id != current_user.id and (not allow_superuser or not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not authorized")
    return media


def get_user_media_ids(current_user, *, processed_only=False) -> list[str]:
    """Return the current user's media IDs through the stable facade."""
    db = get_database_service()
    return db.get_user_media_ids(current_user.id, processed_only=processed_only)


def get_graph_node_media_or_404(node_id, current_user, *, allow_superuser=True):
    """Resolve a graph node to owned media through the stable facade."""
    graph_service = get_knowledge_graph_service()
    video_id = graph_service.get_node_video_id(node_id)
    if not video_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return get_media_or_404(video_id, current_user, allow_superuser=allow_superuser)


__all__ = [
    "AsyncAzureOpenAI",
    "AzureOpenAI",
    "BlobServiceClient",
    "build_blob_sas_url",
    "build_blob_sas_url_async",
    "build_openai_client_kwargs",
    "create_blob_service_client",
    "generate_blob_sas",
    "get_async_graph_service",
    "get_async_openai_client",
    "get_blob_service",
    "get_chat_service",
    "get_chunked_upload_service",
    "get_community_detection_service",
    "get_current_user",
    "get_current_user_optional",
    "get_database_service",
    "get_graph_node_media_or_404",
    "get_graph_route_service",
    "get_graph_search_service",
    "get_hierarchical_context_service",
    "get_hierarchical_query_service",
    "get_knowledge_graph_service",
    "get_media_library_service",
    "get_media_or_404",
    "get_media_upload_service",
    "get_openai_client",
    "get_storage_account_info",
    "get_storage_container_name",
    "get_storage_route_service",
    "get_storage_tiering_service",
    "get_structure_service",
    "get_tool_artifact_service",
    "get_user_media_ids",
    "logger",
    "require_benchmark_operator",
    "require_superuser",
    "security",
    "security_optional",
    "settings",
    "uses_managed_identity_storage",
]
