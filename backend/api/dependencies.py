"""
Shared dependency facade for API routes.

Implementation is split by responsibility across api.*_dependencies modules.
This module keeps the public import surface stable for routes and tests.
"""

import logging

from azure.storage.blob import BlobServiceClient, generate_blob_sas
from openai import AsyncAzureOpenAI, AzureOpenAI

from api.auth_dependencies import (
    get_current_user,
    get_current_user_optional,
    require_benchmark_operator,
    require_superuser,
    security,
    security_optional,
)
from api.azure_dependencies import (
    build_blob_sas_url,
    build_blob_sas_url_async,
    get_async_openai_client,
    get_blob_service,
    get_openai_client,
    get_storage_account_info,
    get_storage_container_name,
)
from api.graph_dependencies import (
    get_async_graph_service,
    get_graph_search_service,
    get_tool_artifact_service,
)
from api.graph_dependencies import (
    get_chat_service as _get_chat_service_impl,
)
from api.graph_dependencies import (
    get_community_detection_service as _get_community_detection_service_impl,
)
from api.graph_dependencies import (
    get_graph_route_service as _get_graph_route_service_impl,
)
from api.graph_dependencies import (
    get_hierarchical_context_service as _get_hierarchical_context_service_impl,
)
from api.graph_dependencies import (
    get_hierarchical_query_service as _get_hierarchical_query_service_impl,
)
from api.graph_dependencies import (
    get_knowledge_graph_service as _get_knowledge_graph_service_impl,
)
from api.graph_dependencies import (
    get_structure_service as _get_structure_service_impl,
)
from api.media_dependencies import (
    get_chunked_upload_service as _get_chunked_upload_service_impl,
)
from api.media_dependencies import (
    get_graph_node_media_or_404 as _get_graph_node_media_or_404_impl,
)
from api.media_dependencies import (
    get_media_library_service as _get_media_library_service_impl,
)
from api.media_dependencies import (
    get_media_or_404 as _get_media_or_404_impl,
)
from api.media_dependencies import (
    get_media_upload_service as _get_media_upload_service_impl,
)
from api.media_dependencies import (
    get_storage_tiering_service as _get_storage_tiering_service_impl,
)
from api.media_dependencies import (
    get_user_media_ids as _get_user_media_ids_impl,
)
from core.azure_credentials import (
    build_openai_client_kwargs,
    create_blob_service_client,
    uses_managed_identity_storage,
)
from core.config import settings
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


def _get_storage_route_service_singleton():
    """Get or create the cached StorageRouteService instance."""
    global _storage_route_service

    if _storage_route_service is None:
        from services.storage_route_service import StorageRouteService

        _storage_route_service = StorageRouteService()
    return _storage_route_service


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service via the stable facade."""
    return _get_knowledge_graph_service_impl()


def get_chat_service(
    *,
    openai_client=None,
    graph_search_service=None,
    service_cls=None,
):
    """Build ChatService while preserving facade-level patch points."""
    return _get_chat_service_impl(
        openai_client=openai_client,
        graph_search_service=graph_search_service,
        service_cls=service_cls,
        openai_client_factory=get_async_openai_client,
        graph_search_service_factory=get_graph_search_service,
    )


def get_structure_service(*, graph_service=None, service_cls=None):
    """Build StructureService while preserving facade-level patch points."""
    return _get_structure_service_impl(
        graph_service=graph_service,
        service_cls=service_cls,
        graph_service_factory=get_knowledge_graph_service,
    )


def get_graph_route_service():
    """Get or create GraphRouteService while preserving facade-level patch points."""
    return _get_graph_route_service_impl(
        knowledge_graph_service_factory=get_knowledge_graph_service,
        graph_search_service_factory=get_graph_search_service,
    )


def get_hierarchical_context_service():
    """Get or create HierarchicalContextService via the stable facade."""
    return _get_hierarchical_context_service_impl(
        graph_service_factory=get_knowledge_graph_service,
    )


def get_hierarchical_query_service():
    """Get or create HierarchicalQueryService via the stable facade."""
    return _get_hierarchical_query_service_impl()


def get_community_detection_service():
    """Get or create CommunityDetectionService via the stable facade."""
    return _get_community_detection_service_impl()


def get_storage_tiering_service():
    """Get or create StorageTieringService via the stable facade."""
    return _get_storage_tiering_service_impl()


def get_storage_route_service():
    """Get or create StorageRouteService via the stable facade."""
    return _get_storage_route_service_singleton()


def get_media_upload_service(
    *,
    blob_service=None,
    db=None,
    container_name=None,
    dispatch_service_factory=None,
):
    """Build MediaUploadService while preserving facade-level patch points."""
    return _get_media_upload_service_impl(
        blob_service=blob_service,
        db=db,
        container_name=container_name,
        dispatch_service_factory=dispatch_service_factory,
        blob_service_factory=get_blob_service,
        db_factory=get_database_service,
        container_name_factory=get_storage_container_name,
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
    return _get_media_library_service_impl(
        db=db,
        blob_service=blob_service,
        container_name=container_name,
        sas_url_factory=sas_url_factory,
        hydrate_data_factory=hydrate_data_factory,
        graph_service_factory=graph_service_factory or get_knowledge_graph_service,
        db_factory=get_database_service,
        blob_service_factory=get_blob_service,
        container_name_factory=get_storage_container_name,
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
    return _get_chunked_upload_service_impl(
        blob_service=blob_service,
        db=db,
        container_name=container_name,
        sas_url_builder=sas_url_builder or build_blob_sas_url_async,
        dispatch_service_factory=dispatch_service_factory,
        blob_service_factory=get_blob_service,
        db_factory=get_database_service,
        container_name_factory=get_storage_container_name,
    )


def get_media_or_404(media_id, current_user, *, allow_superuser=True):
    """Fetch media and enforce ownership through the stable facade."""
    return _get_media_or_404_impl(
        media_id,
        current_user,
        allow_superuser=allow_superuser,
        db_factory=get_database_service,
    )


def get_user_media_ids(current_user, *, processed_only=False) -> list[str]:
    """Return the current user's media IDs through the stable facade."""
    return _get_user_media_ids_impl(
        current_user,
        processed_only=processed_only,
        db_factory=get_database_service,
    )


def get_graph_node_media_or_404(node_id, current_user, *, allow_superuser=True):
    """Resolve a graph node to owned media through the stable facade."""
    return _get_graph_node_media_or_404_impl(
        node_id,
        current_user,
        allow_superuser=allow_superuser,
        graph_service_factory=get_knowledge_graph_service,
        media_getter=get_media_or_404,
    )


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
