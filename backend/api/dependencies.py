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
    get_community_detection_service,
    get_graph_route_service,
    get_graph_search_service,
    get_hierarchical_context_service,
    get_hierarchical_query_service,
    get_knowledge_graph_service,
    get_tool_artifact_service,
)
from api.media_dependencies import (
    get_graph_node_media_or_404,
    get_media_or_404,
    get_storage_tiering_service,
    get_user_media_ids,
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
    "get_media_or_404",
    "get_openai_client",
    "get_storage_account_info",
    "get_storage_container_name",
    "get_storage_tiering_service",
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
